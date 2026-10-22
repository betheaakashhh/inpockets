from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from app.core.config import Settings
from app.core.encryption import FieldEncryptor, keyed_fingerprint
from app.domain import bank_verification as bank_domain
from app.domain.admin import AdminPermission
from app.domain.bank_verification import (
    ACCOUNT_NUMBER_PATTERN,
    IFSC_PATTERN,
    PROVIDER_FAILURE_CODES,
    BankVerificationConflict,
    BankVerificationNotFound,
    BankVerificationRateLimited,
    BankVerificationUnavailable,
    can_transition,
)
from app.domain.bank_verification import (
    BankVerificationStatus as S,
)
from app.models.bank_account_verification import BankAccountVerification
from app.providers.bank_verification import (
    BankAccountVerificationProvider,
    BankProviderRejected,
    BankProviderTimeout,
    BankVerificationResult,
)

# Logs carry ids and statuses only: never account numbers, names or ciphertext.
logger = logging.getLogger(__name__)

ENTITY = "bank_account_verification"


@dataclass(frozen=True)
class DecryptedAccount:
    """Returned only to internal callers (e.g. disbursement). Never serialised."""

    verification_id: uuid.UUID
    user_id: uuid.UUID
    account_number: str
    ifsc: str
    account_last4: str

    def __repr__(self) -> str:
        return f"DecryptedAccount(verification_id={self.verification_id}, last4={self.account_last4})"


class BankVerificationService:
    def __init__(
        self,
        *,
        session,
        repository,
        profile_repository,
        admin_user_repository,
        provider: BankAccountVerificationProvider,
        encryptor_factory,
        audit_log_service,
        admin_authorization_service,
        settings: Settings,
    ):
        self.session = session
        self.repository = repository
        self.profile_repository = profile_repository
        self.admin_user_repository = admin_user_repository
        self.provider = provider
        self._encryptor_factory = encryptor_factory
        self.audit = audit_log_service
        self.admin_authz = admin_authorization_service
        self.settings = settings

    # ------------------------------------------------------------ helpers

    @property
    def encryptor(self) -> FieldEncryptor:
        return self._encryptor_factory()

    @staticmethod
    def _context(row_id: uuid.UUID) -> str:
        return f"bank_account:{row_id}"

    async def _call(self, coro):
        try:
            return await asyncio.wait_for(
                coro, timeout=self.settings.bank_verification_provider_timeout_seconds
            )
        except TimeoutError as exc:
            raise BankProviderTimeout("provider call timed out") from exc

    def _move(self, row, new: S, code: str | None = None) -> None:
        current = S(row.status)
        if current == new:
            return
        if not can_transition(current, new):
            raise BankVerificationConflict(f"Invalid transition: {current} -> {new}")
        row.status = new.value
        if code is not None:
            row.failure_code = code

    async def _audit_system(self, action: str, row, *, reason=None, meta=None) -> None:
        await self.audit.record_system_action(
            action=action,
            entity_type=ENTITY,
            entity_id=str(row.id),
            reason=reason,
            new_value={"status": row.status},
            event_metadata={"provider": row.provider, **(meta or {})},
        )

    async def _holder_name(self, user_id) -> str:
        profile = await self.profile_repository.get_by_user_id(user_id)
        if profile is None or not profile.first_name or not profile.last_name:
            raise ValueError(
                "First name and last name are required before bank verification"
            )
        return f"{profile.first_name} {profile.last_name}".strip()

    @staticmethod
    def normalise(account_number: str, ifsc: str) -> tuple[str, str]:
        account_number = (account_number or "").strip().replace(" ", "")
        ifsc = (ifsc or "").strip().upper()
        if not ACCOUNT_NUMBER_PATTERN.fullmatch(account_number):
            raise ValueError("Invalid account number")
        if not IFSC_PATTERN.fullmatch(ifsc):
            raise ValueError("Invalid IFSC")
        return account_number, ifsc

    # ------------------------------------------------------------ request

    async def request(
        self,
        *,
        actor_user_id: uuid.UUID,
        account_number: str,
        ifsc: str,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> BankAccountVerification:
        """Start (or resume) verification for the caller's own account.

        Idempotent: the same account while one is in flight or already the
        current verified account returns the existing record. Raises
        BankVerificationUnavailable on a provider timeout; the INITIATED row
        is kept (caller must commit) so a retry reuses the client reference.
        """
        account_number, ifsc = self.normalise(account_number, ifsc)
        fingerprint = keyed_fingerprint(f"{account_number}|{ifsc}", settings=self.settings)
        holder = await self._holder_name(actor_user_id)

        await self.repository.lock_user(actor_user_id)

        in_flight = await self.repository.get_in_flight(actor_user_id)
        if in_flight is not None:
            if in_flight.account_fingerprint != fingerprint:
                raise BankVerificationConflict(
                    "Another bank verification is already in progress"
                )
            if S(in_flight.status) == S.INITIATED:
                await self._start(in_flight, account_number, holder)
            return in_flight

        current = await self.repository.get_current_verified(actor_user_id)
        if current is not None and current.account_fingerprint == fingerprint:
            return current

        now = bank_domain.utcnow()
        attempts = await self.repository.count_since(actor_user_id, now - timedelta(hours=24))
        if attempts >= self.settings.bank_verification_max_attempts_per_day:
            raise BankVerificationRateLimited(
                "Too many bank verification attempts; try again later"
            )

        row_id = uuid.uuid4()
        encryptor = self.encryptor
        row = await self.repository.create(
            id=row_id,
            user_id=actor_user_id,
            status=S.INITIATED.value,
            account_number_encrypted=encryptor.encrypt(
                account_number, context=self._context(row_id)
            ),
            encryption_key_id=encryptor.active_key_id,
            account_last4=account_number[-4:],
            account_fingerprint=fingerprint,
            ifsc=ifsc,
            provider=self.provider.name,
            client_reference=f"inp-bank-{row_id}",
            requested_at=now,
            expires_at=now + timedelta(hours=self.settings.bank_verification_pending_timeout_hours),
        )
        await self.audit.record_customer_action(
            actor_user_id=actor_user_id,
            action="BANK_VERIFICATION_REQUESTED",
            entity_type=ENTITY,
            entity_id=str(row.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value={"status": row.status},
            event_metadata={"account_last4": row.account_last4, "ifsc": row.ifsc},
        )
        await self._start(row, account_number, holder)
        return row

    async def _start(self, row, account_number: str, holder: str) -> None:
        try:
            result = await self._call(
                self.provider.verify(
                    client_reference=row.client_reference,
                    account_number=account_number,
                    ifsc=row.ifsc,
                    account_holder_name=holder,
                )
            )
        except BankProviderTimeout as exc:
            await self._audit_system("BANK_VERIFICATION_PROVIDER_TIMEOUT", row)
            raise BankVerificationUnavailable(
                "Bank verification provider is unavailable; retry"
            ) from exc
        except BankProviderRejected:
            self._move(row, S.FAILED, "PROVIDER_REJECTED")
            await self.session.flush()
            await self._audit_system("BANK_VERIFICATION_FAILED", row, reason="PROVIDER_REJECTED")
            return
        await self._apply_result(row, result)

    # ------------------------------------------------------- state changes

    async def _apply_result(self, row, result: BankVerificationResult) -> None:
        if row.provider_ref is None:
            row.provider_ref = result.provider_ref
        elif row.provider_ref != result.provider_ref:
            await self._review(row, "PROVIDER_REFERENCE_MISMATCH")
            return

        status = result.status
        if status == "PENDING":
            self._move(row, S.PENDING)
            await self.session.flush()
            await self._audit_system("BANK_VERIFICATION_PENDING", row)
            return

        row.bank_name = result.bank_name
        row.name_match_result = result.name_match_result

        if status == "FAILED":
            code = (
                result.failure_code
                if result.failure_code in PROVIDER_FAILURE_CODES
                else "VERIFICATION_FAILED"
            )
            self._move(row, S.FAILED, code)
            await self.session.flush()
            await self._audit_system("BANK_VERIFICATION_FAILED", row, reason=code)
            return

        if status != "VERIFIED":
            await self._review(row, "UNEXPECTED_PROVIDER_STATUS")
            return

        match = result.name_match_result
        if match == "MISMATCH":
            self._move(row, S.FAILED, "NAME_MISMATCH")
            await self.session.flush()
            await self._audit_system("BANK_VERIFICATION_FAILED", row, reason="NAME_MISMATCH")
        elif match != "MATCH":
            await self._review(row, f"NAME_MATCH_{match or 'UNAVAILABLE'}")
        elif await self.repository.verified_for_other_user(
            fingerprint=row.account_fingerprint, user_id=row.user_id
        ):
            await self._review(row, "ACCOUNT_SHARED_WITH_OTHER_USER")
        else:
            await self._mark_verified(row)

    async def _review(self, row, code: str) -> None:
        self._move(row, S.MANUAL_REVIEW, code)
        await self.session.flush()
        await self._audit_system("BANK_VERIFICATION_MANUAL_REVIEW", row, reason=code)

    async def _mark_verified(self, row) -> None:
        now = bank_domain.utcnow()
        previous = await self.repository.get_current_verified(row.user_id, for_update=True)
        if previous is not None and previous.id != row.id:
            previous.superseded_at = now
            await self.session.flush()  # free the one-current-per-user slot
        self._move(row, S.VERIFIED)
        row.verified_at = now
        await self.session.flush()
        await self._audit_system("BANK_VERIFICATION_VERIFIED", row)

    # --------------------------------------------------------------- reads

    async def get_current_for_customer(self, *, actor_user_id):
        row = await self.repository.latest_for_user(actor_user_id)
        if row is None:
            raise BankVerificationNotFound("Bank verification not found")
        return row

    async def get_for_admin(self, *, actor_user_id, verification_id, request_id=None, ip_address=None):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.BANK_VERIFICATION_READ
        )
        row = await self.repository.get_by_id(verification_id)
        if row is None:
            raise BankVerificationNotFound("Bank verification not found")
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="BANK_VERIFICATION_VIEWED",
            entity_type=ENTITY,
            entity_id=str(row.id),
            request_id=request_id,
            ip_address=ip_address,
            event_metadata={"subject_user_id": str(row.user_id)},
        )
        return row

    async def list_for_user_admin(self, *, actor_user_id, user_id, request_id=None, ip_address=None):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.BANK_VERIFICATION_READ
        )
        rows = await self.repository.list_for_user(user_id)
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="BANK_VERIFICATION_LIST_VIEWED",
            entity_type="user",
            entity_id=str(user_id),
            request_id=request_id,
            ip_address=ip_address,
            event_metadata={"count": len(rows)},
        )
        return rows

    # ------------------------------------------------------------- review

    async def resolve(
        self,
        *,
        actor_user_id,
        verification_id,
        decision: str,
        reason: str,
        request_id=None,
        ip_address=None,
    ):
        """Admin resolution of a MANUAL_REVIEW verification (VERIFIED/FAILED)."""
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.BANK_VERIFICATION_REVIEW
        )
        if decision not in ("VERIFIED", "FAILED"):
            raise ValueError("Decision must be VERIFIED or FAILED")
        reason = (reason or "").strip()
        if len(reason) < 10:
            raise ValueError("A resolution reason of at least 10 characters is required")

        row = await self.repository.get_by_id(verification_id, for_update=True)
        if row is None:
            raise BankVerificationNotFound("Bank verification not found")
        if row.user_id == actor_user_id:
            raise PermissionError("Admins cannot review their own bank verification")
        if S(row.status) != S.MANUAL_REVIEW:
            raise BankVerificationConflict("Only a verification under review can be resolved")
        if decision == "VERIFIED" and row.provider_ref is None:
            raise BankVerificationConflict(
                "No provider reference exists; this verification can only be rejected"
            )

        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        old = {"status": row.status, "failure_code": row.failure_code}
        row.reviewed_by_admin_user_id = admin.id
        row.reviewed_at = bank_domain.utcnow()
        row.resolution_reason = reason[:500]
        if decision == "VERIFIED":
            await self._mark_verified(row)
        else:
            self._move(row, S.FAILED, "REVIEW_REJECTED")
            await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="BANK_VERIFICATION_RESOLVED",
            entity_type=ENTITY,
            entity_id=str(row.id),
            request_id=request_id,
            ip_address=ip_address,
            reason=reason,
            old_value=old,
            new_value={"status": row.status},
            event_metadata={"subject_user_id": str(row.user_id)},
        )
        return row

    # --------------------------------------------- internal sensitive access

    async def reveal_verified_account(
        self, *, user_id: uuid.UUID, purpose: str, reference: str | None = None
    ) -> DecryptedAccount:
        """Decrypt the current verified account for an internal caller.

        Not exposed over HTTP. Every call is audited (without the number).
        """
        row = await self.repository.get_current_verified(user_id)
        if row is None:
            raise BankVerificationNotFound("No verified bank account")
        number = self.encryptor.decrypt(
            row.account_number_encrypted, context=self._context(row.id)
        )
        await self._audit_system(
            "BANK_ACCOUNT_DECRYPTED",
            row,
            meta={"purpose": purpose, "reference": reference, "account_last4": row.account_last4},
        )
        return DecryptedAccount(
            verification_id=row.id,
            user_id=row.user_id,
            account_number=number,
            ifsc=row.ifsc,
            account_last4=row.account_last4,
        )

    async def reveal_account_by_id(
        self,
        *,
        verification_id: uuid.UUID,
        user_id: uuid.UUID,
        purpose: str,
        reference: str | None = None,
    ) -> DecryptedAccount:
        """Decrypt one specific verified account (e.g. the one a disbursement
        was bound to). Refuses if it is no longer the user's current verified
        account. Audited; not exposed over HTTP.
        """
        row = await self.repository.get_by_id(verification_id)
        if (
            row is None
            or row.user_id != user_id
            or S(row.status) != S.VERIFIED
            or row.superseded_at is not None
        ):
            raise BankVerificationConflict("Bank account is no longer verified for this user")
        number = self.encryptor.decrypt(
            row.account_number_encrypted, context=self._context(row.id)
        )
        await self._audit_system(
            "BANK_ACCOUNT_DECRYPTED",
            row,
            meta={"purpose": purpose, "reference": reference, "account_last4": row.account_last4},
        )
        return DecryptedAccount(
            verification_id=row.id,
            user_id=row.user_id,
            account_number=number,
            ifsc=row.ifsc,
            account_last4=row.account_last4,
        )

    async def rotate_encryption(self, *, batch_size: int = 100) -> int:
        """Re-encrypt rows still using an older key. Caller commits."""
        encryptor = self.encryptor
        rows = await self.repository.list_needing_rotation(
            active_key_id=encryptor.active_key_id, limit=batch_size
        )
        for row in rows:
            ctx = self._context(row.id)
            plain = encryptor.decrypt(row.account_number_encrypted, context=ctx)
            row.account_number_encrypted = encryptor.encrypt(plain, context=ctx)
            row.encryption_key_id = encryptor.active_key_id
        await self.session.flush()
        return len(rows)

    # ---------------------------------------------------------- reconcile

    async def sync_pending(self, *, batch_size: int = 50) -> dict[str, int]:
        """Worker entry point: resolve INITIATED/PENDING verifications.

        Unresolved past expiry => MANUAL_REVIEW (provider outage path).
        Per-record provider errors are counted, not raised. Caller commits.
        """
        counts = {"checked": 0, "updated": 0, "reviewed": 0, "errors": 0}
        now = bank_domain.utcnow()
        rows = await self.repository.list_due(
            statuses=[S.INITIATED.value, S.PENDING.value], limit=batch_size
        )
        for row in rows:
            counts["checked"] += 1
            try:
                if S(row.status) == S.INITIATED:
                    if now >= row.expires_at:
                        await self._review(row, "PROVIDER_UNRESOLVED")
                        counts["reviewed"] += 1
                        continue
                    number = self.encryptor.decrypt(
                        row.account_number_encrypted, context=self._context(row.id)
                    )
                    await self._start(row, number, await self._holder_name(row.user_id))
                    counts["updated"] += 1
                    continue
                result = await self._call(self.provider.get_status(provider_ref=row.provider_ref))
                if result.status != "PENDING":
                    await self._apply_result(row, result)
                    counts["updated"] += 1
                elif now >= row.expires_at:
                    await self._review(row, "PROVIDER_UNRESOLVED")
                    counts["reviewed"] += 1
            except (BankVerificationUnavailable, BankProviderTimeout, BankProviderRejected):
                counts["errors"] += 1
                # A provider that never gives an answer must not leave the
                # customer waiting forever.
                if now >= row.expires_at and S(row.status) in (S.INITIATED, S.PENDING):
                    await self._review(row, "PROVIDER_UNRESOLVED")
                    counts["reviewed"] += 1
        return counts
