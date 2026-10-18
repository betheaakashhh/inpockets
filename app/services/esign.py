from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from app.core.config import Settings
from app.domain import loan_offer as offer_domain
from app.domain.admin import AdminPermission
from app.domain.esign import (
    ESignConflict,
    ESignNotFound,
    ESignStatus,
    ESignUnavailable,
    can_transition,
)
from app.models.esign_transaction import ESignTransaction
from app.providers.esign import (
    ESignProvider,
    ESignProviderRejected,
    ESignProviderTimeout,
)

AGREEMENT_TYPE = "LOAN_AGREEMENT"
SIGNED_TYPE = "SIGNED_AGREEMENT"


@dataclass(frozen=True)
class CallbackResult:
    outcome: str
    transaction_id: uuid.UUID | None = None


class ESignService:
    def __init__(
        self,
        *,
        session,
        repository,
        offer_repository,
        document_repository,
        document_service,
        provider: ESignProvider,
        audit_log_service,
        admin_authorization_service,
        settings: Settings,
    ):
        self.session = session
        self.repository = repository
        self.offer_repository = offer_repository
        self.document_repository = document_repository
        self.document_service = document_service
        self.provider = provider
        self.audit = audit_log_service
        self.admin_authz = admin_authorization_service
        self.settings = settings

    # ------------------------------------------------------------ helpers

    async def _call(self, coro):
        try:
            return await asyncio.wait_for(
                coro, timeout=self.settings.esign_provider_timeout_seconds
            )
        except TimeoutError as exc:
            raise ESignProviderTimeout("provider call timed out") from exc

    def _move(self, tx: ESignTransaction, new: ESignStatus, reason: str | None = None):
        current = ESignStatus(tx.status)
        if current == new:
            return
        if not can_transition(current, new):
            raise ESignConflict(f"Invalid e-sign transition: {current} -> {new}")
        tx.status = new.value
        if reason is not None:
            tx.failure_reason = reason[:255]

    async def _audit(self, action: str, tx: ESignTransaction, *, reason=None, meta=None):
        await self.audit.record_system_action(
            action=action,
            entity_type="esign_transaction",
            entity_id=str(tx.id),
            reason=reason,
            new_value={"status": tx.status},
            event_metadata={
                "loan_offer_id": str(tx.loan_offer_id),
                "loan_offer_version": tx.loan_offer_version,
                "provider": tx.provider,
                **(meta or {}),
            },
        )

    async def _load_agreement(self, offer):
        """Return (document, bytes) after proving the agreement is intact."""
        if offer.agreement_document_id is None:
            raise ESignConflict("Offer has no agreement document")
        doc = await self.document_repository.get_by_id(offer.agreement_document_id)
        if (
            doc is None
            or not doc.is_immutable
            or doc.document_type != AGREEMENT_TYPE
            or doc.content_type != "application/pdf"
            or doc.loan_offer_id != offer.id
            or doc.loan_offer_version != offer.version
        ):
            raise ESignConflict("Agreement document does not match this offer version")
        try:
            stored = await self.document_service.storage.get(doc.storage_ref)
        except FileNotFoundError as exc:
            raise ESignConflict("Agreement document is missing from storage") from exc
        if hashlib.sha256(stored.content).hexdigest() != doc.checksum:
            raise ESignConflict("Agreement document failed its integrity check")
        return doc, stored.content

    async def _owned_offer(self, *, user_id, offer_id, for_update=False):
        getter = (
            self.offer_repository.get_by_id_for_update
            if for_update
            else self.offer_repository.get_by_id
        )
        offer = await getter(offer_id=offer_id)
        if offer is None or offer.user_id != user_id:
            raise ESignNotFound("Loan offer not found")
        return offer

    # ----------------------------------------------------------- initiate

    async def initiate(
        self, *, actor_user_id, offer_id, request_id=None, ip_address=None
    ) -> tuple[ESignTransaction, str | None]:
        """Start (or resume) signing. Idempotent per offer.

        Raises ESignUnavailable if the provider timed out; the INITIATED row
        is kept so a retry reuses the same client reference. The caller must
        commit before reporting the error.
        """
        offer = await self._owned_offer(
            user_id=actor_user_id, offer_id=offer_id, for_update=True
        )
        if offer.status != "ACCEPTED":
            raise ESignConflict("Only an accepted offer can be e-signed")

        tx = await self.repository.get_live_for_offer(offer.id, for_update=True)
        if tx is not None and ESignStatus(tx.status) != ESignStatus.INITIATED:
            return tx, await self._signing_url(tx)

        doc, content = await self._load_agreement(offer)
        if tx is None:
            attempt = await self.repository.count_for_offer(offer.id) + 1
            tx = await self.repository.create(
                user_id=offer.user_id,
                loan_offer_id=offer.id,
                loan_offer_version=offer.version,
                document_id=doc.id,
                document_checksum=doc.checksum,
                provider=self.provider.name,
                client_reference=(
                    f"inp-{offer.id}-v{offer.version}-{doc.checksum[:12]}-a{attempt}"
                ),
                status=ESignStatus.INITIATED.value,
                expires_at=offer_domain.utcnow()
                + timedelta(hours=self.settings.esign_validity_hours),
            )
            await self.audit.record_customer_action(
                actor_user_id=actor_user_id,
                action="ESIGN_INITIATED",
                entity_type="esign_transaction",
                entity_id=str(tx.id),
                request_id=request_id,
                ip_address=ip_address,
                new_value={"status": tx.status},
                event_metadata={
                    "loan_offer_id": str(offer.id),
                    "loan_offer_version": offer.version,
                    "document_checksum": doc.checksum,
                },
            )
        elif tx.document_checksum != doc.checksum:
            raise ESignConflict("Agreement changed since signing was initiated")

        url = await self._start_with_provider(tx, doc, content)
        return tx, url

    async def _start_with_provider(self, tx, doc, content) -> str | None:
        try:
            result = await self._call(
                self.provider.initiate(
                    client_reference=tx.client_reference,
                    signer_user_id=str(tx.user_id),
                    document=content,
                    document_name=f"loan-agreement-v{tx.loan_offer_version}.pdf",
                    document_checksum=doc.checksum,
                )
            )
        except ESignProviderTimeout as exc:
            await self._audit("ESIGN_PROVIDER_TIMEOUT", tx)
            raise ESignUnavailable("E-sign provider is unavailable; retry") from exc
        except ESignProviderRejected:
            self._move(tx, ESignStatus.FAILED, "PROVIDER_REJECTED")
            await self.session.flush()
            await self._audit("ESIGN_FAILED", tx, reason="PROVIDER_REJECTED")
            return None
        tx.provider_ref = result.provider_ref
        self._move(tx, ESignStatus.PENDING)
        await self.session.flush()
        await self._audit("ESIGN_PENDING", tx)
        return result.signing_url

    async def _signing_url(self, tx) -> str | None:
        if ESignStatus(tx.status) != ESignStatus.PENDING or not tx.provider_ref:
            return None
        try:
            return await self._call(
                self.provider.get_signing_url(provider_ref=tx.provider_ref)
            )
        except Exception:  # best effort; never fail a status read
            return None

    # ------------------------------------------------------------- reads

    async def get_for_customer(self, *, actor_user_id, offer_id):
        offer = await self._owned_offer(user_id=actor_user_id, offer_id=offer_id)
        tx = await self.repository.latest_for_offer(offer.id)
        if tx is None:
            raise ESignNotFound("E-sign transaction not found")
        return tx, await self._signing_url(tx)

    async def get_signed_document(
        self, *, actor_user_id, offer_id, request_id=None, ip_address=None
    ):
        offer = await self._owned_offer(user_id=actor_user_id, offer_id=offer_id)
        tx = await self.repository.get_live_for_offer(offer.id)
        if (
            tx is None
            or ESignStatus(tx.status) != ESignStatus.SIGNED
            or tx.signed_document_id is None
        ):
            raise ESignNotFound("Signed agreement not available")
        doc, content = await self.document_service.get_document_for_owner(
            document_id=tx.signed_document_id,
            owner_type="USER",
            owner_id=actor_user_id,
        )
        await self.audit.record_customer_action(
            actor_user_id=actor_user_id,
            action="ESIGN_SIGNED_DOCUMENT_VIEWED",
            entity_type="esign_transaction",
            entity_id=str(tx.id),
            request_id=request_id,
            ip_address=ip_address,
            event_metadata={"document_id": str(doc.id)},
        )
        return tx, doc, content

    async def get_for_admin(self, *, actor_user_id, offer_id):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.LOAN_APPLICATION_READ
        )
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if offer is None:
            raise ESignNotFound("Loan offer not found")
        tx = await self.repository.latest_for_offer(offer.id)
        if tx is None:
            raise ESignNotFound("E-sign transaction not found")
        return tx, await self.repository.list_events(tx.id)

    # ---------------------------------------------------------- callbacks

    async def handle_callback(
        self, *, provider_name: str, headers: Mapping[str, str], body: bytes
    ) -> CallbackResult:
        """Verify, deduplicate and apply one provider callback.

        Raises ESignSignatureInvalid / ESignCallbackMalformed (provider
        errors), ESignNotFound for an unknown provider or reference, and
        ESignUnavailable for transient trouble (caller rolls back so the
        provider retries). Everything else commits as one unit.
        """
        if provider_name.lower() != self.provider.name:
            raise ESignNotFound("Unknown provider")
        cb = self.provider.verify_callback(headers=headers, body=body)

        tx = await self.repository.get_by_provider_ref_for_update(
            provider=self.provider.name, provider_ref=cb.provider_ref
        )
        if tx is None:
            # Not stored: the provider may call back before we have recorded
            # its reference (timeout case); it should retry.
            raise ESignNotFound("Unknown transaction reference")

        event_id = await self.repository.insert_event(
            provider=self.provider.name,
            provider_event_id=cb.event_id,
            provider_ref=cb.provider_ref,
            esign_transaction_id=tx.id,
            reported_status=cb.status,
            payload={
                "event_id": cb.event_id,
                "provider_ref": cb.provider_ref,
                "status": cb.status,
                "document_checksum": cb.document_checksum,
                "occurred_at": cb.occurred_at.isoformat() if cb.occurred_at else None,
                "failure_reason": cb.failure_reason,
                "has_signed_document": cb.signed_document is not None,
            },
        )
        if event_id is None:
            return CallbackResult("DUPLICATE", tx.id)

        outcome = await self._apply_report(
            tx,
            status=cb.status,
            checksum=cb.document_checksum,
            occurred_at=cb.occurred_at,
            failure_reason=cb.failure_reason,
            signed_document=cb.signed_document,
        )
        await self.repository.update_event(event_id, outcome=outcome)
        return CallbackResult(outcome, tx.id)

    async def _apply_report(
        self, tx, *, status, checksum, occurred_at, failure_reason, signed_document
    ) -> str:
        current = ESignStatus(tx.status)
        now = offer_domain.utcnow()

        if current == ESignStatus.SIGNED:
            same = status == "SIGNED" and checksum == tx.document_checksum
            outcome = "DUPLICATE_SIGNED" if same else "IGNORED_AFTER_SIGNED"
            if not same:
                await self._audit(
                    "ESIGN_CONFLICTING_CALLBACK_IGNORED", tx, meta={"reported": status}
                )
            return outcome
        if current == ESignStatus.MANUAL_REVIEW:
            return "IGNORED_IN_REVIEW"

        if checksum is not None and checksum != tx.document_checksum:
            return await self._review(tx, "DOCUMENT_MISMATCH")

        if status == "PENDING":
            return "PROCESSED"

        if status == "SIGNED":
            if current != ESignStatus.PENDING:
                return await self._review(tx, "LATE_SIGNED")
            if checksum is None:
                return await self._review(tx, "SIGNED_WITHOUT_DOCUMENT_REFERENCE")
            if now > tx.expires_at and (occurred_at is None or occurred_at > tx.expires_at):
                return await self._review(tx, "SIGNED_AFTER_EXPIRY")
            return await self._complete_signing(tx, occurred_at, signed_document, now)

        if current != ESignStatus.PENDING and current != ESignStatus.INITIATED:
            return "IGNORED_TERMINAL"
        target = ESignStatus.FAILED if status == "FAILED" else ESignStatus.EXPIRED
        self._move(tx, target, failure_reason or status)
        await self.session.flush()
        await self._audit(f"ESIGN_{target.value}", tx, reason=failure_reason)
        return "PROCESSED"

    async def _review(self, tx, reason: str) -> str:
        self._move(tx, ESignStatus.MANUAL_REVIEW, reason)
        await self.session.flush()
        await self._audit("ESIGN_MANUAL_REVIEW", tx, reason=reason)
        return reason

    async def _complete_signing(self, tx, occurred_at, signed_document, now) -> str:
        artifact = signed_document
        if artifact is None:
            try:
                artifact = await self._call(
                    self.provider.fetch_signed_document(provider_ref=tx.provider_ref)
                )
            except ESignProviderTimeout as exc:
                raise ESignUnavailable("Signed document fetch timed out") from exc
            except ESignProviderRejected:
                artifact = None

        signed_doc = None
        if artifact is None:
            if self.settings.esign_require_signed_artifact:
                return await self._review(tx, "SIGNED_ARTIFACT_UNAVAILABLE")
        else:
            original = await self.document_repository.get_by_id(tx.document_id)
            try:
                signed_doc = await self.document_service.store_document(
                    owner_type="USER",
                    owner_id=tx.user_id,
                    document_type=SIGNED_TYPE,
                    content=artifact,
                    content_type="application/pdf",
                    key_hint=f"signed-agreement-v{tx.loan_offer_version}",
                    immutable=True,
                    loan_offer_id=tx.loan_offer_id,
                    loan_offer_version=tx.loan_offer_version,
                    template_key=original.template_key,
                    template_version=original.template_version,
                )
            except ValueError:
                return await self._review(tx, "SIGNED_ARTIFACT_INVALID")

        if signed_doc is not None:
            tx.signed_document_id = signed_doc.id
            tx.signed_checksum = signed_doc.checksum
        tx.signed_at = occurred_at if occurred_at and occurred_at <= now else now
        self._move(tx, ESignStatus.SIGNED)
        await self.session.flush()
        await self._audit(
            "ESIGN_SIGNED",
            tx,
            meta={"signed_document_id": str(tx.signed_document_id)},
        )
        return "SIGNED"

    # --------------------------------------------------------- reconcile

    async def sync_pending(self, *, batch_size: int = 50) -> dict[str, int]:
        """Worker entry point: resolve INITIATED/PENDING transactions.

        The caller commits. Per-transaction provider errors are counted, not
        raised, so one bad record cannot block the batch.
        """
        counts = {"checked": 0, "expired": 0, "updated": 0, "errors": 0}
        now = offer_domain.utcnow()
        rows = await self.repository.list_due(
            statuses=[ESignStatus.INITIATED.value, ESignStatus.PENDING.value],
            limit=batch_size,
        )
        for tx in rows:
            counts["checked"] += 1
            try:
                if ESignStatus(tx.status) == ESignStatus.INITIATED:
                    if now >= tx.expires_at:
                        self._move(tx, ESignStatus.EXPIRED, "EXPIRED")
                        await self._audit("ESIGN_EXPIRED", tx)
                        counts["expired"] += 1
                        continue
                    offer = await self.offer_repository.get_by_id(
                        offer_id=tx.loan_offer_id
                    )
                    doc, content = await self._load_agreement(offer)
                    await self._start_with_provider(tx, doc, content)
                    counts["updated"] += 1
                    continue

                report = await self._call(
                    self.provider.get_status(provider_ref=tx.provider_ref)
                )
                if report.status in ("SIGNED", "FAILED", "EXPIRED"):
                    await self._apply_report(
                        tx,
                        status=report.status,
                        checksum=report.document_checksum,
                        occurred_at=None,
                        failure_reason=report.failure_reason,
                        signed_document=None,
                    )
                    counts["updated"] += 1
                elif now >= tx.expires_at:
                    self._move(tx, ESignStatus.EXPIRED, "EXPIRED")
                    await self.session.flush()
                    await self._audit("ESIGN_EXPIRED", tx)
                    counts["expired"] += 1
            except (ESignUnavailable, ESignProviderTimeout, ESignProviderRejected, ESignConflict):
                counts["errors"] += 1
        return counts
