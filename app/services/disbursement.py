from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from app.core.config import Settings
from app.domain import disbursement as dom
from app.domain.admin import AdminPermission
from app.domain.bank_verification import BankVerificationConflict, BankVerificationNotFound
from app.domain.disbursement import (
    FAILURE_CODES,
    DisbursementConflict,
    DisbursementNotFound,
    DisbursementUnavailable,
    can_transition,
)
from app.domain.disbursement import (
    DisbursementStatus as S,
)
from app.models.disbursement import Disbursement
from app.providers.disbursement import (
    DisbursementProvider,
    DisbursementProviderRejected,
    DisbursementProviderTimeout,
)

# Logs carry ids and statuses only: never account numbers or names.
logger = logging.getLogger(__name__)

ENTITY = "disbursement"


@dataclass(frozen=True)
class WebhookResult:
    outcome: str
    disbursement_id: object | None = None


class DisbursementService:
    def __init__(
        self,
        *,
        session,
        repository,
        offer_repository,
        esign_repository,
        bank_repository,
        bank_service,
        profile_repository,
        admin_user_repository,
        ledger_service,
        provider: DisbursementProvider,
        audit_log_service,
        admin_authorization_service,
        settings: Settings,
    ):
        self.session = session
        self.repository = repository
        self.offer_repository = offer_repository
        self.esign_repository = esign_repository
        self.bank_repository = bank_repository
        self.bank_service = bank_service
        self.profile_repository = profile_repository
        self.admin_user_repository = admin_user_repository
        self.ledger = ledger_service
        self.provider = provider
        self.audit = audit_log_service
        self.admin_authz = admin_authorization_service
        self.settings = settings

    # ------------------------------------------------------------ helpers

    async def _call(self, coro):
        try:
            return await asyncio.wait_for(
                coro, timeout=self.settings.disbursement_provider_timeout_seconds
            )
        except TimeoutError as exc:
            raise DisbursementProviderTimeout("provider call timed out") from exc

    def _move(self, d: Disbursement, new: S, *, code: str | None = None) -> None:
        current = S(d.status)
        if current == new:
            return
        if not can_transition(current, new):
            raise DisbursementConflict(f"Invalid disbursement transition: {current} -> {new}")
        d.status = new.value
        if code is not None:
            d.failure_code = code

    async def _audit_system(self, action: str, d: Disbursement, *, reason=None, meta=None):
        await self.audit.record_system_action(
            action=action,
            entity_type=ENTITY,
            entity_id=str(d.id),
            reason=reason,
            new_value={"status": d.status},
            event_metadata={
                "loan_offer_id": str(d.loan_offer_id),
                "provider": d.provider,
                "attempt": d.attempt,
                **(meta or {}),
            },
        )

    @staticmethod
    def _failure(code: str | None) -> str:
        return code if code in FAILURE_CODES else "PROVIDER_FAILED"

    # --------------------------------------------------------- creation

    async def create_for_offer(
        self, *, actor_user_id, offer_id, request_id=None, ip_address=None
    ) -> Disbursement:
        """Record a PENDING disbursement for an accepted, e-signed offer.

        The amount comes from the stored offer, never from the request.
        Idempotent: an existing live disbursement is returned unchanged.
        """
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.DISBURSEMENT_EXECUTE
        )
        offer = await self.offer_repository.get_by_id_for_update(offer_id=offer_id)
        if offer is None:
            raise DisbursementNotFound("Loan offer not found")
        live = await self.repository.get_live_for_offer(offer.id)
        if live is not None:
            return live
        d = await self._new_row(offer, actor_user_id=actor_user_id, retry_of=None)
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="DISBURSEMENT_CREATED",
            entity_type=ENTITY,
            entity_id=str(d.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value={"status": d.status, "amount": str(d.amount)},
            event_metadata={"loan_offer_id": str(offer.id), "beneficiary_last4": d.beneficiary_last4},
        )
        return d

    async def _new_row(self, offer, *, actor_user_id, retry_of) -> Disbursement:
        if offer.status != "ACCEPTED":
            raise DisbursementConflict("Only an accepted offer can be disbursed")
        esign = await self.esign_repository.get_live_for_offer(offer.id)
        if esign is None or esign.status != "SIGNED":
            raise DisbursementConflict("The agreement has not been e-signed")
        bank = await self.bank_repository.get_current_verified(offer.user_id)
        if bank is None:
            raise DisbursementConflict("The customer has no verified bank account")
        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        attempt = await self.repository.count_for_offer(offer.id) + 1
        return await self.repository.create(
            user_id=offer.user_id,
            loan_application_id=offer.loan_application_id,
            loan_offer_id=offer.id,
            loan_offer_version=offer.version,
            esign_transaction_id=esign.id,
            bank_verification_id=bank.id,
            amount=offer.principal_amount,
            currency="INR",
            beneficiary_last4=bank.account_last4,
            beneficiary_ifsc=bank.ifsc,
            status=S.PENDING.value,
            attempt=attempt,
            retry_of_id=retry_of.id if retry_of else None,
            idempotency_key=f"inp-disb-{offer.id}-a{attempt}",
            provider=self.provider.name,
            requested_by_admin_user_id=admin.id if admin else None,
            requested_at=dom.utcnow(),
        )

    # ------------------------------------------------------ worker steps

    async def claim_pending(self, *, batch_size: int = 20) -> list:
        """Move PENDING rows to PROCESSING (caller commits) so that a crash
        after this point is recovered by reconciliation, not by re-claiming."""
        rows = await self.repository.list_pending_for_claim(limit=batch_size)
        now = dom.utcnow()
        for d in rows:
            self._move(d, S.PROCESSING)
            d.dispatched_at = now
            d.dispatch_attempts += 1
            await self._audit_system("DISBURSEMENT_PROCESSING", d)
        await self.session.flush()
        return [d.id for d in rows]

    async def submit_claimed(self, disbursement_id) -> str:
        """Send one claimed disbursement to the provider (caller commits).

        Harmless if run twice: a row another worker holds is skipped, and a
        row that already has a provider reference is never re-sent here.
        """
        d = await self.repository.get_by_id(disbursement_id, for_update=True, skip_locked=True)
        if d is None:
            return "SKIPPED_LOCKED"
        if S(d.status) != S.PROCESSING or d.provider_ref is not None:
            return "SKIPPED"
        return await self._submit(d)

    async def _submit(self, d: Disbursement) -> str:
        try:
            account = await self.bank_service.reveal_account_by_id(
                verification_id=d.bank_verification_id,
                user_id=d.user_id,
                purpose="DISBURSEMENT",
                reference=str(d.id),
            )
            profile = await self.profile_repository.get_by_user_id(d.user_id)
            if profile is None or not profile.first_name or not profile.last_name:
                raise BankVerificationNotFound("beneficiary name missing")
        except (BankVerificationConflict, BankVerificationNotFound):
            return await self._review(d, "BENEFICIARY_UNAVAILABLE")
        name = f"{profile.first_name} {profile.last_name}".strip()

        try:
            result = await self._call(
                self.provider.submit(
                    idempotency_key=d.idempotency_key,
                    amount=d.amount,
                    currency=d.currency,
                    beneficiary_account_number=account.account_number,
                    beneficiary_ifsc=account.ifsc,
                    beneficiary_name=name,
                    narration=f"InPockets loan {d.loan_offer_id}",
                )
            )
        except DisbursementProviderTimeout:
            # Unknown: money may have moved. Stay PROCESSING; reconcile decides.
            await self._audit_system("DISBURSEMENT_PROVIDER_TIMEOUT", d)
            return "UNKNOWN"
        except DisbursementProviderRejected as exc:
            self._move(d, S.FAILED, code=self._failure(exc.code))
            await self.session.flush()
            await self._audit_system("DISBURSEMENT_FAILED", d, reason=d.failure_code)
            return "FAILED"
        return await self._apply(
            d,
            status=result.status,
            provider_ref=result.provider_ref,
            utr=result.utr,
            failure_code=result.failure_code,
        )

    async def reconcile_candidates(self, *, limit: int = 50) -> list:
        now = dom.utcnow()
        grace = timedelta(minutes=self.settings.disbursement_reconcile_grace_minutes)
        return await self.repository.list_reconcile_candidate_ids(
            dispatched_before=now - grace, polled_before=now - grace, limit=limit
        )

    async def reconcile_one(self, disbursement_id) -> str:
        """Resolve one uncertain PROCESSING disbursement (caller commits)."""
        d = await self.repository.get_by_id(disbursement_id, for_update=True, skip_locked=True)
        if d is None:
            return "SKIPPED_LOCKED"
        if S(d.status) != S.PROCESSING:
            return "SKIPPED"
        now = dom.utcnow()
        age = now - (d.dispatched_at or d.requested_at)
        too_old = age >= timedelta(hours=self.settings.disbursement_max_unresolved_hours)
        d.last_polled_at = now
        try:
            report = await self._call(
                self.provider.get_status(
                    idempotency_key=d.idempotency_key, provider_ref=d.provider_ref
                )
            )
        except DisbursementProviderTimeout:
            await self._audit_system("DISBURSEMENT_POLL_TIMEOUT", d)
            return await self._review(d, "PROVIDER_UNRESOLVED") if too_old else "UNKNOWN"

        if report.status == "NOT_FOUND":
            if d.provider_ref is not None:
                return await self._review(d, "PROVIDER_REF_NOT_FOUND")
            # The provider never saw the key: re-sending is safe, because the
            # provider dedupes on the idempotency key.
            d.dispatch_attempts += 1
            return await self._submit(d)
        outcome = await self._apply(
            d,
            status=report.status,
            provider_ref=report.provider_ref,
            utr=report.utr,
            amount=report.amount,
            failure_code=report.failure_code,
        )
        if outcome == "PROCESSING" and too_old:
            return await self._review(d, "UNRESOLVED_TOO_LONG")
        return outcome

    # --------------------------------------------------- state application

    async def _apply(
        self,
        d: Disbursement,
        *,
        status: str,
        provider_ref: str | None = None,
        utr: str | None = None,
        amount=None,
        failure_code: str | None = None,
        from_review: bool = False,
    ) -> str:
        """Apply a provider-reported status. The single place state changes."""
        cur = S(d.status)
        now = dom.utcnow()

        if provider_ref:
            if d.provider_ref is None:
                d.provider_ref = provider_ref
            elif d.provider_ref != provider_ref:
                if cur in (S.SUCCESS, S.REVERSED):
                    await self._audit_system("DISBURSEMENT_CONFLICT_IGNORED", d,
                                             meta={"why": "provider_ref_mismatch"})
                    return "IGNORED_TERMINAL"
                return await self._review(d, "PROVIDER_REF_MISMATCH")

        if cur == S.REVERSED:
            return "IGNORED_TERMINAL"

        if amount is not None and amount != d.amount:
            if cur == S.SUCCESS:
                await self._audit_system("DISBURSEMENT_CONFLICT_IGNORED", d,
                                         meta={"why": "amount_mismatch"})
                return "AMOUNT_MISMATCH_IGNORED"
            return await self._review(d, "AMOUNT_MISMATCH")

        if cur == S.SUCCESS:
            if status == "SUCCESS":
                return "DUPLICATE_SUCCESS"
            if status == "REVERSED":
                self._move(d, S.REVERSED)
                d.reversed_at = now
                await self.session.flush()
                await self.ledger.reverse_disbursement(d)
                await self._audit_system("DISBURSEMENT_REVERSED", d)
                return "REVERSED"
            await self._audit_system("DISBURSEMENT_CONFLICT_IGNORED", d,
                                     meta={"why": "report_after_success", "reported": status})
            return "IGNORED_AFTER_SUCCESS"

        if cur == S.FAILED:
            if status in ("SUCCESS", "REVERSED"):
                return await self._review(d, "LATE_SUCCESS_AFTER_FAILURE")
            return "IGNORED_AFTER_FAILURE"

        if cur == S.REQUIRES_REVIEW and not from_review:
            return "IGNORED_IN_REVIEW"

        if cur == S.PENDING:
            return await self._review(d, "UNEXPECTED_REPORT_BEFORE_DISPATCH")

        # PROCESSING, or REQUIRES_REVIEW during an admin recheck.
        if status == "PROCESSING":
            return "PROCESSING"
        if status == "FAILED":
            self._move(d, S.FAILED, code=self._failure(failure_code))
            d.review_reason = None
            await self.session.flush()
            await self._audit_system("DISBURSEMENT_FAILED", d, reason=d.failure_code)
            return "FAILED"
        if status in ("SUCCESS", "REVERSED"):
            if d.provider_ref is None:
                return await self._review(d, "SUCCESS_WITHOUT_PROVIDER_REF")
            self._move(d, S.SUCCESS)
            d.utr = utr
            d.completed_at = now
            d.review_reason = None
            await self.session.flush()
            # The books move in the same transaction as the payout state.
            await self.ledger.post_disbursement(d)
            await self._audit_system("DISBURSEMENT_SUCCESS", d)
            if status == "REVERSED":
                self._move(d, S.REVERSED)
                d.reversed_at = now
                await self.session.flush()
                await self.ledger.reverse_disbursement(d)
                await self._audit_system("DISBURSEMENT_REVERSED", d)
                return "REVERSED"
            return "SUCCESS"
        return await self._review(d, "UNEXPECTED_PROVIDER_STATUS")

    async def _review(self, d: Disbursement, reason: str) -> str:
        if S(d.status) == S.REQUIRES_REVIEW:
            return reason
        self._move(d, S.REQUIRES_REVIEW)
        d.review_reason = reason[:100]
        await self.session.flush()
        await self._audit_system("DISBURSEMENT_REQUIRES_REVIEW", d, reason=reason)
        return reason

    # ---------------------------------------------------------- webhooks

    async def handle_webhook(
        self, *, provider_name: str, headers: Mapping[str, str], body: bytes
    ) -> WebhookResult:
        """Verify, deduplicate and apply one provider callback.

        Raises the provider's signature/malformed errors, DisbursementNotFound
        for an unknown provider or reference (provider should retry).
        """
        if provider_name.lower() != self.provider.name:
            raise DisbursementNotFound("Unknown provider")
        cb = self.provider.verify_webhook(headers=headers, body=body)

        d = await self.repository.get_by_provider_ref_for_update(
            provider=self.provider.name, provider_ref=cb.provider_ref
        )
        if d is None and cb.idempotency_key:
            d = await self.repository.get_by_idempotency_key_for_update(cb.idempotency_key)
        if d is None:
            raise DisbursementNotFound("Unknown disbursement reference")

        event_id = await self.repository.insert_event(
            provider=self.provider.name,
            provider_event_id=cb.event_id,
            provider_ref=cb.provider_ref,
            disbursement_id=d.id,
            reported_status=cb.status,
            payload={
                "event_id": cb.event_id,
                "provider_ref": cb.provider_ref,
                "status": cb.status,
                "amount": str(cb.amount) if cb.amount is not None else None,
                "utr": cb.utr,
                "failure_code": cb.failure_code,
                "occurred_at": cb.occurred_at.isoformat() if cb.occurred_at else None,
            },
        )
        if event_id is None:
            return WebhookResult("DUPLICATE", d.id)

        outcome = await self._apply(
            d,
            status=cb.status,
            provider_ref=cb.provider_ref,
            utr=cb.utr,
            amount=cb.amount,
            failure_code=cb.failure_code,
        )
        await self.repository.set_event_outcome(event_id, outcome)
        return WebhookResult(outcome, d.id)

    # ------------------------------------------------------- admin actions

    async def retry(
        self, *, actor_user_id, disbursement_id, reason: str, request_id=None, ip_address=None
    ) -> Disbursement:
        """Manual retry of a FAILED or REVERSED disbursement as a new attempt."""
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.DISBURSEMENT_RETRY
        )
        reason = (reason or "").strip()
        if len(reason) < 10:
            raise DisbursementConflict("A reason of at least 10 characters is required")
        first = await self.repository.get_by_id(disbursement_id)
        if first is None:
            raise DisbursementNotFound("Disbursement not found")
        # Same lock order as creation: offer, then disbursement.
        offer = await self.offer_repository.get_by_id_for_update(offer_id=first.loan_offer_id)
        d = await self.repository.get_by_id(disbursement_id, for_update=True)
        if S(d.status) not in (S.FAILED, S.REVERSED):
            raise DisbursementConflict("Only a failed or reversed disbursement can be retried")
        if await self.repository.get_live_for_offer(offer.id) is not None:
            raise DisbursementConflict("Another disbursement for this offer is already live")

        if S(d.status) == S.FAILED:
            # Prove the provider really did not pay before paying again.
            try:
                report = await self._call(
                    self.provider.get_status(
                        idempotency_key=d.idempotency_key, provider_ref=d.provider_ref
                    )
                )
            except DisbursementProviderTimeout as exc:
                raise DisbursementUnavailable("Provider could not be reached to verify") from exc
            if report.status not in ("NOT_FOUND", "FAILED"):
                await self._review(d, "RETRY_BLOCKED_PROVIDER_STATE")
                conflict = DisbursementConflict(
                    "Provider reports this payout is not failed; sent to review"
                )
                conflict.persist = True  # the review move must be committed
                raise conflict

        new = await self._new_row(offer, actor_user_id=actor_user_id, retry_of=d)
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="DISBURSEMENT_RETRIED",
            entity_type=ENTITY,
            entity_id=str(new.id),
            request_id=request_id,
            ip_address=ip_address,
            reason=reason,
            old_value={"disbursement_id": str(d.id), "status": d.status},
            new_value={"status": new.status, "attempt": new.attempt},
            event_metadata={"loan_offer_id": str(offer.id)},
        )
        return new

    async def recheck(
        self, *, actor_user_id, disbursement_id, request_id=None, ip_address=None
    ) -> tuple[Disbursement, str]:
        """Ask the provider about a PROCESSING / REQUIRES_REVIEW payout now.

        An admin never sets a status: only what the provider reports counts.
        """
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.DISBURSEMENT_EXECUTE
        )
        d = await self.repository.get_by_id(disbursement_id, for_update=True)
        if d is None:
            raise DisbursementNotFound("Disbursement not found")
        cur = S(d.status)
        if cur not in (S.PROCESSING, S.REQUIRES_REVIEW):
            raise DisbursementConflict("Only an unresolved disbursement can be rechecked")
        try:
            report = await self._call(
                self.provider.get_status(
                    idempotency_key=d.idempotency_key, provider_ref=d.provider_ref
                )
            )
        except DisbursementProviderTimeout as exc:
            raise DisbursementUnavailable("Provider could not be reached") from exc
        d.last_polled_at = dom.utcnow()
        if report.status == "NOT_FOUND":
            if cur == S.REQUIRES_REVIEW:
                outcome = await self._apply(
                    d, status="FAILED", failure_code="PROVIDER_NOT_FOUND", from_review=True
                )
            else:
                outcome = "NOT_FOUND_YET"
        else:
            outcome = await self._apply(
                d,
                status=report.status,
                provider_ref=report.provider_ref,
                utr=report.utr,
                amount=report.amount,
                failure_code=report.failure_code,
                from_review=cur == S.REQUIRES_REVIEW,
            )
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="DISBURSEMENT_RECHECKED",
            entity_type=ENTITY,
            entity_id=str(d.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"status": cur.value},
            new_value={"status": d.status},
            event_metadata={"outcome": outcome},
        )
        return d, outcome

    # --------------------------------------------------------------- reads

    async def get_for_customer(self, *, actor_user_id, offer_id) -> Disbursement:
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if offer is None or offer.user_id != actor_user_id:
            raise DisbursementNotFound("Disbursement not found")
        d = await self.repository.latest_for_offer(offer.id)
        if d is None:
            raise DisbursementNotFound("Disbursement not found")
        return d

    async def get_for_admin(self, *, actor_user_id, disbursement_id):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.DISBURSEMENT_READ
        )
        d = await self.repository.get_by_id(disbursement_id)
        if d is None:
            raise DisbursementNotFound("Disbursement not found")
        return d, await self.repository.list_events(d.id)

    async def list_for_admin(self, *, actor_user_id, status=None, loan_offer_id=None, limit=100):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.DISBURSEMENT_READ
        )
        return await self.repository.list_filtered(
            status=status, loan_offer_id=loan_offer_id, limit=min(limit, 200)
        )
