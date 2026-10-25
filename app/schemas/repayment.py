from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain import repayment as dom


class ScheduleCreateRequest(BaseModel):
    """Only the loan and a count: amounts and dates come from stored records."""

    model_config = ConfigDict(extra="forbid")

    loan_offer_id: uuid.UUID
    installment_count: int = Field(default=1, ge=1, le=dom.MAX_INSTALLMENTS)
    interval_days: int | None = Field(default=None, ge=1, le=dom.MAX_INTERVAL_DAYS)


class ScheduleCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class InstallmentResponse(BaseModel):
    installment_number: int
    due_date: date
    status: str  # SCHEDULED | PARTIALLY_PAID | PAID | OVERDUE (derived)
    principal_due: Decimal
    interest_due: Decimal
    fee_due: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    fee_paid: Decimal
    remaining: Decimal

    @classmethod
    def from_row(cls, i, today: date) -> InstallmentResponse:
        remaining = (
            (i.principal_due - i.principal_paid)
            + (i.interest_due - i.interest_paid)
            + (i.fee_due - i.fee_paid)
        )
        return cls(
            installment_number=i.installment_number,
            due_date=i.due_date,
            status=dom.effective_status(i.status, i.due_date, today),
            principal_due=i.principal_due,
            interest_due=i.interest_due,
            fee_due=i.fee_due,
            principal_paid=i.principal_paid,
            interest_paid=i.interest_paid,
            fee_paid=i.fee_paid,
            remaining=remaining,
        )


class ScheduleResponse(BaseModel):
    id: uuid.UUID
    loan_offer_id: uuid.UUID
    status: str
    principal_total: Decimal
    interest_total: Decimal
    fee_total: Decimal
    total_payable: Decimal
    total_paid: Decimal
    total_remaining: Decimal
    installment_count: int
    interval_days: int
    first_due_date: date
    activated_at: datetime | None
    installments: list[InstallmentResponse]

    @classmethod
    def from_rows(cls, schedule, installments) -> ScheduleResponse:
        today = dom.today_ist()
        items = [InstallmentResponse.from_row(i, today) for i in installments]
        paid = sum(
            (i.principal_paid + i.interest_paid + i.fee_paid for i in installments), Decimal(0)
        )
        return cls(
            id=schedule.id,
            loan_offer_id=schedule.loan_offer_id,
            status=schedule.status,
            principal_total=schedule.principal_total,
            interest_total=schedule.interest_total,
            fee_total=schedule.fee_total,
            total_payable=schedule.total_payable,
            total_paid=paid,
            total_remaining=schedule.total_payable - paid,
            installment_count=schedule.installment_count,
            interval_days=schedule.interval_days,
            first_due_date=schedule.first_due_date,
            activated_at=schedule.activated_at,
            installments=items,
        )


class AdminScheduleResponse(ScheduleResponse):
    user_id: uuid.UUID
    disbursement_id: uuid.UUID
    ledger_principal_outstanding: Decimal | None = None
    schedule_principal_outstanding: Decimal | None = None
    ledger_matches_schedule: bool | None = None

    @classmethod
    def from_admin_rows(cls, schedule, installments, ledger_principal) -> AdminScheduleResponse:
        base = ScheduleResponse.from_rows(schedule, installments)
        schedule_principal = sum(
            (i.principal_due - i.principal_paid for i in installments), Decimal(0)
        )
        return cls(
            **base.model_dump(),
            user_id=schedule.user_id,
            disbursement_id=schedule.disbursement_id,
            ledger_principal_outstanding=ledger_principal,
            schedule_principal_outstanding=schedule_principal,
            ledger_matches_schedule=ledger_principal == schedule_principal,
        )


class PaymentCreateRequest(BaseModel):
    """The customer states an intent to pay. No status field exists here: a
    client can never mark a payment successful."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class PaymentResponse(BaseModel):
    """Customer view: no provider detail, no internal uncertainty."""

    id: uuid.UUID
    loan_offer_id: uuid.UUID
    status: str  # PROCESSING | PAID | FAILED | REVERSED
    amount: Decimal
    currency: str
    checkout_url: str | None = None
    requested_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_row(cls, p) -> PaymentResponse:
        status = dom.PaymentStatus(p.status)
        customer_status = dom.CUSTOMER_STATUS[status]
        return cls(
            id=p.id,
            loan_offer_id=p.loan_offer_id,
            status=customer_status,
            amount=p.amount,
            currency=p.currency,
            checkout_url=p.checkout_url if customer_status == "PROCESSING" else None,
            requested_at=p.requested_at,
            completed_at=p.completed_at,
        )


class PaymentEventResponse(BaseModel):
    provider_event_id: str
    reported_status: str
    outcome: str
    received_at: datetime


class AdminPaymentResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    loan_offer_id: uuid.UUID
    schedule_id: uuid.UUID
    status: str
    amount: Decimal
    currency: str
    client_idempotency_key: str
    idempotency_key: str
    provider: str
    provider_ref: str | None
    failure_code: str | None
    review_reason: str | None
    principal_applied: Decimal
    interest_applied: Decimal
    fee_applied: Decimal
    unapplied_amount: Decimal
    dispatch_attempts: int
    requested_at: datetime
    dispatched_at: datetime | None
    last_polled_at: datetime | None
    completed_at: datetime | None
    reversed_at: datetime | None
    events: list[PaymentEventResponse] = []

    @classmethod
    def from_row(cls, p, events=()) -> AdminPaymentResponse:
        return cls(
            id=p.id,
            user_id=p.user_id,
            loan_offer_id=p.loan_offer_id,
            schedule_id=p.schedule_id,
            status=p.status,
            amount=p.amount,
            currency=p.currency,
            client_idempotency_key=p.client_idempotency_key,
            idempotency_key=p.idempotency_key,
            provider=p.provider,
            provider_ref=p.provider_ref,
            failure_code=p.failure_code,
            review_reason=p.review_reason,
            principal_applied=p.principal_applied,
            interest_applied=p.interest_applied,
            fee_applied=p.fee_applied,
            unapplied_amount=p.unapplied_amount,
            dispatch_attempts=p.dispatch_attempts,
            requested_at=p.requested_at,
            dispatched_at=p.dispatched_at,
            last_polled_at=p.last_polled_at,
            completed_at=p.completed_at,
            reversed_at=p.reversed_at,
            events=[
                PaymentEventResponse(
                    provider_event_id=e.provider_event_id,
                    reported_status=e.reported_status,
                    outcome=e.outcome,
                    received_at=e.received_at,
                )
                for e in events
            ],
        )


class PaymentRecheckResponse(BaseModel):
    outcome: str
    payment: AdminPaymentResponse
