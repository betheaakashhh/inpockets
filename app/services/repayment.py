from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from app.core.config import Settings
from app.domain import pricing as pricing_dom
from app.domain import repayment as dom
from app.domain.admin import AdminPermission
from app.domain.repayment import (
    FAILURE_CODES,
    MAX_OPEN_PAYMENTS_PER_SCHEDULE,
    InstallmentState,
    RepaymentConflict,
    RepaymentNotFound,
    RepaymentUnavailable,
    can_transition,
)
from app.domain.repayment import PaymentStatus as S
from app.models.repayment import RepaymentPayment
from app.repositories.pricing import PricingRepository
from app.providers.payment import (
    PaymentProvider,
    PaymentProviderRejected,
    PaymentProviderTimeout,
)

# Logs carry ids and statuses only.
logger = logging.getLogger(__name__)

PAYMENT = "repayment_payment"
SCHEDULE = "repayment_schedule"
_CLIENT_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


@dataclass(frozen=True)
class WebhookResult:
    outcome: str
    payment_id: object | None = None


def _state(i) -> InstallmentState:
    return InstallmentState(
        id=i.id,
        number=i.installment_number,
        due_date=i.due_date,
        principal_due=i.principal_due,
        interest_due=i.interest_due,
        fee_due=i.fee_due,
        principal_paid=i.principal_paid,
        interest_paid=i.interest_paid,
        fee_paid=i.fee_paid,
    )


class RepaymentService:
    def __init__(
        self,
        *,
        session,
        repository,
        offer_repository,
        disbursement_repository,
        ledger_service,
        admin_user_repository,
        provider: PaymentProvider,
        audit_log_service,
        admin_authorization_service,
        settings: Settings,
    ):
        self.session = session
        self.repository = repository
        self.offer_repository = offer_repository
        self.disbursement_repository = disbursement_repository
        self.ledger = ledger_service
        self.admin_user_repository = admin_user_repository
        self.provider = provider
        self.audit = audit_log_service
        self.admin_authz = admin_authorization_service
        self.settings = settings
        self.pricing_repository = PricingRepository(session)

    # ------------------------------------------------------------ helpers

    async def _call(self, coro):
        try:
            return await asyncio.wait_for(
                coro, timeout=self.settings.payment_provider_timeout_seconds
            )
        except TimeoutError as exc:
            raise PaymentProviderTimeout("provider call timed out") from exc

    def _move(self, p: RepaymentPayment, new: S, *, code: str | None = None) -> None:
        current = S(p.status)
        if current == new:
            return
        if not can_transition(current, new):
            raise RepaymentConflict(f"Invalid payment transition: {current} -> {new}")
        p.status = new.value
        if code is not None:
            p.failure_code = code

    async def _audit_system(self, action: str, p: RepaymentPayment, *, reason=None, meta=None):
        await self.audit.record_system_action(
            action=action,
            entity_type=PAYMENT,
            entity_id=str(p.id),
            reason=reason,
            new_value={"status": p.status},
            event_metadata={
                "loan_offer_id": str(p.loan_offer_id),
                "provider": p.provider,
                **(meta or {}),
            },
        )

    @staticmethod
    def _failure(code: str | None) -> str:
        return code if code in FAILURE_CODES else "PROVIDER_FAILED"

    async def _paid_disbursement(self, offer_id):
        d = await self.disbursement_repository.get_live_for_offer(offer_id)
        if d is None or d.status != "SUCCESS":
            raise RepaymentConflict("The loan has not been disbursed")
        return d

    async def _lock(self, payment_id, *, skip_locked: bool = False):
        """Lock order is always schedule -> payment, everywhere."""
        first = await self.repository.get_payment(payment_id)
        if first is None:
            raise RepaymentNotFound("Payment not found")
        schedule = await self.repository.get_schedule(first.schedule_id, for_update=True)
        payment = await self.repository.get_payment(
            payment_id, for_update=True, skip_locked=skip_locked
        )
        return payment, schedule

    # ------------------------------------------------------------ schedule

    async def create_schedule(
        self,
        *,
        actor_user_id,
        offer_id,
        installment_count: int | None = None,
        interval_days: int | None = None,
        request_id=None,
        ip_address=None,
    ):
        """DRAFT schedule from the stored offer and the disbursed amount.

        Nothing about the commercial terms comes from the request: the
        principal is what was actually disbursed, the period is bounded by the
        offer tenure, and interest appears only if the offer itself states a
        rate (and the accounting rules for posting it are enabled)."""
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.REPAYMENT_SCHEDULE_MANAGE
        )
        offer = await self.offer_repository.get_by_id_for_update(offer_id=offer_id)
        if offer is None:
            raise RepaymentNotFound("Loan offer not found")
        disbursement = await self._paid_disbursement(offer.id)
        if await self.repository.get_live_schedule_for_offer(offer.id) is not None:
            raise RepaymentConflict("A repayment schedule already exists for this loan")

        snapshot = await self.pricing_repository.get_snapshot(offer.id)
        start = dom.today_ist(disbursement.completed_at)
        if snapshot is not None:
            # Priced loan: the schedule IS the offer's frozen terms (monthly
            # EMIs on a reducing balance). The request may not change them.
            if installment_count is not None and installment_count != snapshot.months:
                raise RepaymentConflict("The instalment count is fixed by the offer")
            if interval_days is not None and interval_days != pricing_dom.MONTH_DAYS:
                raise RepaymentConflict("The instalment interval is fixed by the offer")
            if disbursement.amount != snapshot.net_payout:
                raise RepaymentConflict("The disbursed amount does not match the offer")
            try:
                emi_rows = pricing_dom.emi_schedule(
                    principal=snapshot.principal,
                    annual_interest_percent=snapshot.annual_interest_percent,
                    months=snapshot.months,
                    start=start,
                )
            except pricing_dom.PricingError as exc:
                raise RepaymentConflict(str(exc)) from exc
            plans = [
                dom.InstallmentPlan(
                    number=r.number,
                    due_date=r.due_date,
                    principal_due=r.principal,
                    interest_due=r.interest,
                    fee_due=Decimal("0.00"),
                )
                for r in emi_rows
            ]
            installment_count = snapshot.months
            interval = pricing_dom.MONTH_DAYS
        else:
            installment_count = installment_count or 1
            interval = interval_days or max(1, offer.tenure_days // installment_count)
            if interval * installment_count > offer.tenure_days:
                raise RepaymentConflict("The schedule would run past the offer tenure")
            rate = (offer.commercial_terms or {}).get("interest_rate_percent_per_annum")
            try:
                rate = Decimal(str(rate)) if rate not in (None, "") else None
            except InvalidOperation as exc:
                raise RepaymentConflict("The offer has an unreadable interest rate") from exc
            plans = dom.build_schedule(
                principal=disbursement.amount,
                count=installment_count,
                start=start,
                interval_days=interval,
                annual_rate_percent=rate,
            )
        principal_total = sum((p.principal_due for p in plans), Decimal(0))
        interest_total = sum((p.interest_due for p in plans), Decimal(0))
        fee_total = sum((p.fee_due for p in plans), Decimal(0))
        if (interest_total > 0 or fee_total > 0) and not (
            self.settings.ledger_interest_fee_posting_enabled
        ):
            raise RepaymentConflict(
                "Interest and fees cannot be scheduled until the accounting rules for "
                "posting them are approved and enabled"
            )
        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        schedule = await self.repository.create_schedule(
            user_id=offer.user_id,
            loan_offer_id=offer.id,
            disbursement_id=disbursement.id,
            status="DRAFT",
            principal_total=principal_total,
            interest_total=interest_total,
            fee_total=fee_total,
            total_payable=principal_total + interest_total + fee_total,
            installment_count=installment_count,
            interval_days=interval,
            first_due_date=plans[0].due_date,
            created_by_admin_user_id=admin.id if admin else None,
        )
        await self.repository.add_installments(
            [
                {
                    "schedule_id": schedule.id,
                    "installment_number": p.number,
                    "due_date": p.due_date,
                    "principal_due": p.principal_due,
                    "interest_due": p.interest_due,
                    "fee_due": p.fee_due,
                    "principal_paid": Decimal("0.00"),
                    "interest_paid": Decimal("0.00"),
                    "fee_paid": Decimal("0.00"),
                    "status": "SCHEDULED",
                }
                for p in plans
            ]
        )
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="REPAYMENT_SCHEDULE_CREATED",
            entity_type=SCHEDULE,
            entity_id=str(schedule.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value={
                "status": "DRAFT",
                "total_payable": str(schedule.total_payable),
                "installments": installment_count,
            },
            event_metadata={"loan_offer_id": str(offer.id)},
        )
        return schedule

    async def _lock_draft(self, schedule_id):
        first = await self.repository.get_schedule(schedule_id)
        if first is None:
            raise RepaymentNotFound("Repayment schedule not found")
        # Same order as creation: offer, then schedule.
        offer = await self.offer_repository.get_by_id_for_update(offer_id=first.loan_offer_id)
        schedule = await self.repository.get_schedule(schedule_id, for_update=True)
        if schedule.status != "DRAFT":
            raise RepaymentConflict("Only a draft schedule can be changed")
        return offer, schedule

    async def activate_schedule(self, *, actor_user_id, schedule_id, request_id=None, ip_address=None):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.REPAYMENT_SCHEDULE_MANAGE
        )
        offer, schedule = await self._lock_draft(schedule_id)
        await self._paid_disbursement(offer.id)
        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        schedule.status = "ACTIVE"
        schedule.activated_at = dom.utcnow()
        schedule.activated_by_admin_user_id = admin.id if admin else None
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="REPAYMENT_SCHEDULE_ACTIVATED",
            entity_type=SCHEDULE,
            entity_id=str(schedule.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"status": "DRAFT"},
            new_value={"status": "ACTIVE"},
            event_metadata={"loan_offer_id": str(offer.id)},
        )
        return schedule

    async def cancel_schedule(
        self, *, actor_user_id, schedule_id, reason: str, request_id=None, ip_address=None
    ):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.REPAYMENT_SCHEDULE_MANAGE
        )
        reason = (reason or "").strip()
        if len(reason) < 10:
            raise RepaymentConflict("A reason of at least 10 characters is required")
        offer, schedule = await self._lock_draft(schedule_id)
        schedule.status = "CANCELLED"
        schedule.cancelled_at = dom.utcnow()
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="REPAYMENT_SCHEDULE_CANCELLED",
            entity_type=SCHEDULE,
            entity_id=str(schedule.id),
            request_id=request_id,
            ip_address=ip_address,
            reason=reason,
            old_value={"status": "DRAFT"},
            new_value={"status": "CANCELLED"},
            event_metadata={"loan_offer_id": str(offer.id)},
        )
        return schedule

    # ------------------------------------------------------------ payments

    async def initiate_payment(
        self, *, actor_user_id, offer_id, amount, client_key: str, request_id=None, ip_address=None
    ) -> tuple[RepaymentPayment, bool]:
        """Record a payment attempt (DB only; the caller commits, then calls
        dispatch_payment). The amount is the customer's *intent*: nothing about
        it, or about success, is trusted afterwards.

        Idempotent per (customer, Idempotency-Key): a replay returns the same
        payment; the same key with a different request is refused."""
        if not _CLIENT_KEY.match(client_key or ""):
            raise dom.RepaymentError("Idempotency-Key must be 8-100 URL-safe characters")
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if offer is None or offer.user_id != actor_user_id:
            raise RepaymentNotFound("Loan not found")
        schedule = await self.repository.get_active_schedule_for_offer(offer.id, for_update=True)
        if schedule is None:
            raise RepaymentConflict("There is no active repayment schedule for this loan")

        try:
            requested = Decimal(str(amount))
        except InvalidOperation as exc:
            raise dom.RepaymentError("Invalid amount") from exc
        if not requested.is_finite() or requested <= 0 or requested != dom.q(requested):
            raise dom.RepaymentError("Amount must be positive with at most two decimals")

        existing = await self.repository.get_payment_by_client_key(actor_user_id, client_key)
        if existing is not None:
            if existing.loan_offer_id == offer.id and existing.amount == requested:
                return existing, False
            raise RepaymentConflict("Idempotency-Key was already used for a different request")

        installments = await self.repository.list_installments(schedule.id)
        outstanding = sum((_state(i).outstanding for i in installments), Decimal(0))
        if outstanding <= 0:
            raise RepaymentConflict("This loan is fully repaid")
        if requested > outstanding:
            raise RepaymentConflict(f"Amount exceeds the outstanding balance of {outstanding}")
        if await self.repository.count_open_payments(schedule.id) >= MAX_OPEN_PAYMENTS_PER_SCHEDULE:
            raise RepaymentConflict("Too many payments are already in progress for this loan")

        payment_id = uuid.uuid4()
        payment = await self.repository.create_payment(
            id=payment_id,
            user_id=offer.user_id,
            loan_offer_id=offer.id,
            schedule_id=schedule.id,
            amount=requested,
            currency="INR",
            status=S.INITIATED.value,
            client_idempotency_key=client_key,
            idempotency_key=f"inp-pay-{payment_id}",
            provider=self.provider.name,
            requested_at=dom.utcnow(),
        )
        await self.audit.record_customer_action(
            actor_user_id=actor_user_id,
            action="REPAYMENT_INITIATED",
            entity_type=PAYMENT,
            entity_id=str(payment.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value={"status": payment.status, "amount": str(payment.amount)},
            event_metadata={"loan_offer_id": str(offer.id)},
        )
        return payment, True

    async def dispatch_payment(self, payment_id) -> str:
        """Ask the provider to open the collection (caller commits).

        The provider call happens with NO row locks held. It is idempotent on
        the payment's key, so a duplicate or retried dispatch cannot create a
        second collection; the result is applied under the usual locks."""
        p = await self.repository.get_payment(payment_id)
        if p is None:
            raise RepaymentNotFound("Payment not found")
        if S(p.status) != S.INITIATED or p.provider_ref is not None:
            return "SKIPPED"
        key, amount, currency, ref = p.idempotency_key, p.amount, p.currency, str(p.id)

        outcome: tuple | None = None
        try:
            result = await self._call(
                self.provider.create_payment(
                    idempotency_key=key, amount=amount, currency=currency, reference=ref
                )
            )
            outcome = ("result", result)
        except PaymentProviderTimeout:
            outcome = ("timeout", None)
        except PaymentProviderRejected as exc:
            outcome = ("rejected", exc.code)

        p, _schedule = await self._lock(payment_id)
        if S(p.status) != S.INITIATED:
            return "SKIPPED"
        p.dispatch_attempts += 1
        p.dispatched_at = dom.utcnow()
        kind, value = outcome
        if kind == "timeout":
            # Unknown: the collection may exist. Stay INITIATED; the worker
            # retries with the same key, which the provider dedupes.
            await self._audit_system("REPAYMENT_PROVIDER_TIMEOUT", p)
            return "UNKNOWN"
        if kind == "rejected":
            self._move(p, S.FAILED, code=self._failure(value))
            await self.session.flush()
            await self._audit_system("REPAYMENT_FAILED", p, reason=p.failure_code)
            return "FAILED"
        return await self._apply(
            p,
            status=value.status,
            provider_ref=value.provider_ref,
            failure_code=value.failure_code,
            checkout_url=value.checkout_url,
        )

    # ------------------------------------------------------ state changes

    async def _apply(
        self,
        p: RepaymentPayment,
        *,
        status: str,
        provider_ref: str | None = None,
        amount=None,
        failure_code: str | None = None,
        checkout_url: str | None = None,
        from_review: bool = False,
    ) -> str:
        """Apply provider-reported state. Caller holds schedule + payment locks."""
        cur = S(p.status)

        if provider_ref:
            if p.provider_ref is None:
                p.provider_ref = provider_ref
            elif p.provider_ref != provider_ref:
                if cur in (S.SUCCESS, S.REVERSED):
                    await self._audit_system(
                        "REPAYMENT_CONFLICT_IGNORED", p, meta={"why": "provider_ref_mismatch"}
                    )
                    return "IGNORED_TERMINAL"
                return await self._review(p, "PROVIDER_REF_MISMATCH")

        if cur == S.REVERSED:
            return "IGNORED_TERMINAL"

        if amount is not None and amount != p.amount:
            if cur == S.SUCCESS:
                await self._audit_system(
                    "REPAYMENT_CONFLICT_IGNORED", p, meta={"why": "amount_mismatch"}
                )
                return "AMOUNT_MISMATCH_IGNORED"
            return await self._review(p, "AMOUNT_MISMATCH")

        if cur == S.SUCCESS:
            if status == "SUCCESS":
                return "DUPLICATE_SUCCESS"
            if status == "REVERSED":
                await self._reverse(p)
                return "REVERSED"
            await self._audit_system(
                "REPAYMENT_CONFLICT_IGNORED", p, meta={"why": "report_after_success", "reported": status}
            )
            return "IGNORED_AFTER_SUCCESS"

        if cur == S.FAILED:
            if status in ("SUCCESS", "REVERSED"):
                return await self._review(p, "LATE_SUCCESS_AFTER_FAILURE")
            return "IGNORED_AFTER_FAILURE"

        if cur == S.REQUIRES_REVIEW and not from_review:
            return "IGNORED_IN_REVIEW"

        if status == "PENDING":
            if cur == S.INITIATED:
                self._move(p, S.PENDING)
                p.checkout_url = checkout_url
                await self.session.flush()
                await self._audit_system("REPAYMENT_PENDING", p)
            return "PENDING"
        if status == "FAILED":
            self._move(p, S.FAILED, code=self._failure(failure_code))
            p.review_reason = None
            await self.session.flush()
            await self._audit_system("REPAYMENT_FAILED", p, reason=p.failure_code)
            return "FAILED"
        if status in ("SUCCESS", "REVERSED"):
            if p.provider_ref is None:
                return await self._review(p, "SUCCESS_WITHOUT_PROVIDER_REF")
            await self._settle(p)
            if status == "REVERSED":
                await self._reverse(p)
                return "REVERSED"
            return "SUCCESS"
        return await self._review(p, "UNEXPECTED_PROVIDER_STATUS")

    async def _settle(self, p: RepaymentPayment) -> None:
        """Verified money in: allocate to installments and post the ledger,
        in the caller's transaction (all of it commits or none of it does)."""
        rows = await self.repository.list_installments(p.schedule_id, for_update=True)
        by_id = {r.id: r for r in rows}
        allocations, unapplied = dom.allocate([_state(r) for r in rows], p.amount)

        principal = interest = fees = Decimal("0.00")
        for a in allocations:
            row = by_id[a.installment_id]
            row.fee_paid += a.fee
            row.interest_paid += a.interest
            row.principal_paid += a.principal
            row.status = dom.stored_status(_state(row)).value
            principal += a.principal
            interest += a.interest
            fees += a.fee
        await self.repository.add_allocations(
            [
                {
                    "payment_id": p.id,
                    "installment_id": a.installment_id,
                    "fee_amount": a.fee,
                    "interest_amount": a.interest,
                    "principal_amount": a.principal,
                }
                for a in allocations
            ]
        )
        p.principal_applied = principal
        p.interest_applied = interest
        p.fee_applied = fees
        p.unapplied_amount = unapplied
        self._move(p, S.SUCCESS)
        p.completed_at = dom.utcnow()
        p.review_reason = None
        await self.session.flush()
        await self.ledger.post_repayment(
            payment=p, principal=principal, interest=interest, fees=fees, unapplied=unapplied
        )
        await self._audit_system(
            "REPAYMENT_SUCCESS",
            p,
            meta={"principal": str(principal), "interest": str(interest),
                  "fees": str(fees), "unapplied": str(unapplied)},
        )
        if unapplied > 0:
            await self._audit_system(
                "REPAYMENT_UNAPPLIED_RECEIPT", p, reason="RECEIPT_EXCEEDS_OUTSTANDING",
                meta={"unapplied": str(unapplied)},
            )

    async def _reverse(self, p: RepaymentPayment) -> None:
        """Undo exactly what this payment did, then post the mirror entries."""
        rows = await self.repository.list_installments(p.schedule_id, for_update=True)
        by_id = {r.id: r for r in rows}
        for a in await self.repository.list_allocations(p.id):
            row = by_id[a.installment_id]
            row.fee_paid -= a.fee_amount
            row.interest_paid -= a.interest_amount
            row.principal_paid -= a.principal_amount
            row.status = dom.stored_status(_state(row)).value
        self._move(p, S.REVERSED)
        p.reversed_at = dom.utcnow()
        await self.session.flush()
        await self.ledger.reverse_repayment(p)
        await self._audit_system("REPAYMENT_REVERSED", p)

    async def _review(self, p: RepaymentPayment, reason: str) -> str:
        if S(p.status) == S.REQUIRES_REVIEW:
            return reason
        self._move(p, S.REQUIRES_REVIEW)
        p.review_reason = reason[:100]
        await self.session.flush()
        await self._audit_system("REPAYMENT_REQUIRES_REVIEW", p, reason=reason)
        return reason

    # ------------------------------------------------------------ webhooks

    async def handle_webhook(
        self, *, provider_name: str, headers: Mapping[str, str], body: bytes
    ) -> WebhookResult:
        """Verify, deduplicate and apply one provider callback."""
        if provider_name.lower() != self.provider.name:
            raise RepaymentNotFound("Unknown provider")
        cb = self.provider.verify_webhook(headers=headers, body=body)

        found = await self.repository.get_payment_by_provider_ref(
            provider=self.provider.name, provider_ref=cb.provider_ref
        )
        if found is None and cb.idempotency_key:
            found = await self.repository.get_payment_by_idempotency_key(cb.idempotency_key)
        if found is None:
            raise RepaymentNotFound("Unknown payment reference")
        p, _schedule = await self._lock(found.id)

        event_id = await self.repository.insert_event(
            provider=self.provider.name,
            provider_event_id=cb.event_id,
            provider_ref=cb.provider_ref,
            payment_id=p.id,
            reported_status=cb.status,
            payload={
                "event_id": cb.event_id,
                "provider_ref": cb.provider_ref,
                "status": cb.status,
                "amount": str(cb.amount) if cb.amount is not None else None,
                "failure_code": cb.failure_code,
                "occurred_at": cb.occurred_at.isoformat() if cb.occurred_at else None,
            },
        )
        if event_id is None:
            return WebhookResult("DUPLICATE", p.id)
        outcome = await self._apply(
            p,
            status=cb.status,
            provider_ref=cb.provider_ref,
            amount=cb.amount,
            failure_code=cb.failure_code,
        )
        await self.repository.set_event_outcome(event_id, outcome)
        return WebhookResult(outcome, p.id)

    # ------------------------------------------------------ worker steps

    async def undispatched_candidates(self, *, limit: int = 50) -> list:
        grace = timedelta(minutes=1)
        return await self.repository.list_undispatched_ids(
            requested_before=dom.utcnow() - grace, limit=limit
        )

    async def reconcile_candidates(self, *, limit: int = 50) -> list:
        now = dom.utcnow()
        grace = timedelta(minutes=self.settings.payment_reconcile_grace_minutes)
        return await self.repository.list_reconcile_candidate_ids(
            requested_before=now - grace, polled_before=now - grace, limit=limit
        )

    async def reconcile_one(self, payment_id) -> str:
        """Resolve one PENDING payment from the provider's own record (caller
        commits). The provider is asked with no locks held."""
        p = await self.repository.get_payment(payment_id)
        if p is None or S(p.status) != S.PENDING:
            return "SKIPPED"
        key, ref = p.idempotency_key, p.provider_ref
        try:
            report = await self._call(self.provider.get_status(idempotency_key=key, provider_ref=ref))
        except PaymentProviderTimeout:
            p, _ = await self._lock(payment_id)
            p.last_polled_at = dom.utcnow()
            await self._audit_system("REPAYMENT_POLL_TIMEOUT", p)
            return await self._maybe_too_old(p, "UNKNOWN")

        locked = await self._lock(payment_id, skip_locked=True)
        p = locked[0]
        if p is None:
            return "SKIPPED_LOCKED"
        if S(p.status) != S.PENDING:
            return "SKIPPED"
        p.last_polled_at = dom.utcnow()
        if report.status == "NOT_FOUND":
            return await self._review(p, "PROVIDER_REF_NOT_FOUND")
        outcome = await self._apply(
            p,
            status=report.status,
            provider_ref=report.provider_ref,
            amount=report.amount,
            failure_code=report.failure_code,
        )
        return await self._maybe_too_old(p, outcome)

    async def _maybe_too_old(self, p: RepaymentPayment, outcome: str) -> str:
        if outcome in ("PENDING", "UNKNOWN") and S(p.status) == S.PENDING:
            age = dom.utcnow() - p.requested_at
            if age >= timedelta(hours=self.settings.payment_max_unresolved_hours):
                return await self._review(p, "UNRESOLVED_TOO_LONG")
        return outcome

    # ------------------------------------------------------- admin actions

    async def recheck(self, *, actor_user_id, payment_id, request_id=None, ip_address=None):
        """Ask the provider about an unresolved payment now. An admin never
        sets a status: only what the provider reports counts."""
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.REPAYMENT_REVIEW
        )
        first = await self.repository.get_payment(payment_id)
        if first is None:
            raise RepaymentNotFound("Payment not found")
        if S(first.status) not in (S.INITIATED, S.PENDING, S.REQUIRES_REVIEW):
            raise RepaymentConflict("Only an unresolved payment can be rechecked")
        try:
            report = await self._call(
                self.provider.get_status(
                    idempotency_key=first.idempotency_key, provider_ref=first.provider_ref
                )
            )
        except PaymentProviderTimeout as exc:
            raise RepaymentUnavailable("Provider could not be reached") from exc
        p, _schedule = await self._lock(payment_id)
        cur = S(p.status)
        if cur not in (S.INITIATED, S.PENDING, S.REQUIRES_REVIEW):
            raise RepaymentConflict("Only an unresolved payment can be rechecked")
        p.last_polled_at = dom.utcnow()
        from_review = cur == S.REQUIRES_REVIEW
        if report.status == "NOT_FOUND":
            if from_review:
                outcome = await self._apply(
                    p, status="FAILED", failure_code="PROVIDER_NOT_FOUND", from_review=True
                )
            else:
                outcome = "NOT_FOUND_YET"
        else:
            outcome = await self._apply(
                p,
                status=report.status,
                provider_ref=report.provider_ref,
                amount=report.amount,
                failure_code=report.failure_code,
                from_review=from_review,
            )
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="REPAYMENT_RECHECKED",
            entity_type=PAYMENT,
            entity_id=str(p.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"status": cur.value},
            new_value={"status": p.status},
            event_metadata={"outcome": outcome},
        )
        return p, outcome

    # --------------------------------------------------------------- reads

    async def _installments_view(self, schedule):
        rows = await self.repository.list_installments(schedule.id)
        return rows

    async def get_schedule_for_customer(self, *, actor_user_id, offer_id):
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if offer is None or offer.user_id != actor_user_id:
            raise RepaymentNotFound("Repayment schedule not found")
        schedule = await self.repository.get_active_schedule_for_offer(offer.id)
        if schedule is None:
            raise RepaymentNotFound("Repayment schedule not found")
        return schedule, await self.repository.list_installments(schedule.id)

    async def list_payments_for_customer(self, *, actor_user_id, offer_id):
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if offer is None or offer.user_id != actor_user_id:
            raise RepaymentNotFound("Loan not found")
        return await self.repository.list_payments_for_offer(offer.id, user_id=actor_user_id)

    async def get_payment_for_customer(self, *, actor_user_id, payment_id):
        p = await self.repository.get_payment(payment_id)
        if p is None or p.user_id != actor_user_id:
            raise RepaymentNotFound("Payment not found")
        return p

    async def _require_read(self, actor_user_id):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.REPAYMENT_READ
        )

    async def get_schedule_for_admin(self, *, actor_user_id, schedule_id):
        await self._require_read(actor_user_id)
        schedule = await self.repository.get_schedule(schedule_id)
        if schedule is None:
            raise RepaymentNotFound("Repayment schedule not found")
        installments = await self.repository.list_installments(schedule.id)
        principal_in_ledger = await self.ledger.principal_outstanding(schedule.loan_offer_id)
        return schedule, installments, principal_in_ledger

    async def list_schedules_for_admin(self, *, actor_user_id, loan_offer_id=None, limit=100):
        await self._require_read(actor_user_id)
        return await self.repository.list_schedules(loan_offer_id=loan_offer_id, limit=min(limit, 200))

    async def get_payment_for_admin(self, *, actor_user_id, payment_id):
        await self._require_read(actor_user_id)
        p = await self.repository.get_payment(payment_id)
        if p is None:
            raise RepaymentNotFound("Payment not found")
        return p, await self.repository.list_events(p.id)

    async def list_payments_for_admin(self, *, actor_user_id, status=None, loan_offer_id=None, limit=100):
        await self._require_read(actor_user_id)
        return await self.repository.list_payments_filtered(
            status=status, loan_offer_id=loan_offer_id, limit=min(limit, 200)
        )
