from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MONEY = Numeric(12, 2)


def _uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


class RepaymentSchedule(Base):
    """Agreed repayment plan for one disbursed loan. Immutable once ACTIVE."""

    __tablename__ = "repayment_schedules"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','ACTIVE','CANCELLED')", name="ck_schedule_status"),
        CheckConstraint("principal_total > 0", name="ck_schedule_principal_positive"),
        CheckConstraint("interest_total >= 0 AND fee_total >= 0", name="ck_schedule_nonneg"),
        CheckConstraint(
            "total_payable = principal_total + interest_total + fee_total",
            name="ck_schedule_total",
        ),
        CheckConstraint("installment_count >= 1", name="ck_schedule_count"),
        CheckConstraint("(status = 'ACTIVE') = (activated_at IS NOT NULL)", name="ck_schedule_activated"),
        CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL)", name="ck_schedule_cancelled"),
        Index("ix_schedule_user", "user_id"),
        Index(
            "uq_schedule_one_live_per_offer",
            "loan_offer_id",
            unique=True,
            postgresql_where=text("status IN ('DRAFT','ACTIVE')"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    disbursement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disbursements.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    principal_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    interest_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_payable: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    installment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    first_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    activated_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    activated_at: Mapped[datetime | None] = _ts()
    cancelled_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())


class RepaymentInstallment(Base):
    """Due amounts are immutable; only the paid amounts and status move."""

    __tablename__ = "repayment_installments"
    __table_args__ = (
        UniqueConstraint("schedule_id", "installment_number", name="uq_installment_number"),
        CheckConstraint("installment_number >= 1", name="ck_installment_number"),
        CheckConstraint("principal_due > 0 AND interest_due >= 0 AND fee_due >= 0", name="ck_installment_due"),
        CheckConstraint(
            "principal_paid >= 0 AND interest_paid >= 0 AND fee_paid >= 0 "
            "AND principal_paid <= principal_due AND interest_paid <= interest_due "
            "AND fee_paid <= fee_due",
            name="ck_installment_paid_within_due",
        ),
        CheckConstraint("status IN ('SCHEDULED','PARTIALLY_PAID','PAID')", name="ck_installment_status"),
        CheckConstraint(
            "(status = 'PAID') = (principal_paid = principal_due AND interest_paid = interest_due "
            "AND fee_paid = fee_due)",
            name="ck_installment_paid_status",
        ),
        CheckConstraint(
            "(status = 'SCHEDULED') = (principal_paid = 0 AND interest_paid = 0 AND fee_paid = 0)",
            name="ck_installment_scheduled_status",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_schedules.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    principal_due: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    interest_due: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_due: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    principal_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    interest_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    fee_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="SCHEDULED")
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())


class RepaymentPayment(Base):
    """One customer payment attempt. Only verified provider state (a signed
    webhook or our own server-to-server lookup) ever moves it to SUCCESS."""

    __tablename__ = "repayment_payments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_idempotency_key"),
        UniqueConstraint("user_id", "client_idempotency_key", name="uq_payment_client_key"),
        UniqueConstraint("provider", "provider_ref", name="uq_payment_provider_ref"),
        CheckConstraint(
            "status IN ('INITIATED','PENDING','SUCCESS','FAILED','REVERSED','REQUIRES_REVIEW')",
            name="ck_payment_status",
        ),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        CheckConstraint(
            "principal_applied >= 0 AND interest_applied >= 0 AND fee_applied >= 0 "
            "AND unapplied_amount >= 0",
            name="ck_payment_applied_nonneg",
        ),
        CheckConstraint(
            "status NOT IN ('SUCCESS','REVERSED') OR provider_ref IS NOT NULL",
            name="ck_payment_provider_ref_when_paid",
        ),
        CheckConstraint(
            "(status IN ('SUCCESS','REVERSED')) = (completed_at IS NOT NULL)",
            name="ck_payment_completed_iff_paid",
        ),
        CheckConstraint(
            "(status = 'REVERSED') = (reversed_at IS NOT NULL)", name="ck_payment_reversed_at"
        ),
        CheckConstraint(
            "status NOT IN ('SUCCESS','REVERSED') OR "
            "principal_applied + interest_applied + fee_applied + unapplied_amount = amount",
            name="ck_payment_fully_accounted",
        ),
        Index("ix_payment_status_requested", "status", "requested_at"),
        Index("ix_payment_schedule", "schedule_id"),
        Index("ix_payment_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="INITIATED")
    client_idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    checkout_url: Mapped[str | None] = mapped_column(String(500))
    failure_code: Mapped[str | None] = mapped_column(String(50))
    review_reason: Mapped[str | None] = mapped_column(String(100))
    principal_applied: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    interest_applied: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    fee_applied: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    unapplied_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    dispatched_at: Mapped[datetime | None] = _ts()
    last_polled_at: Mapped[datetime | None] = _ts()
    completed_at: Mapped[datetime | None] = _ts()
    reversed_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())


class RepaymentAllocation(Base):
    """How one successful payment was applied. Append-only: a reversal reads
    these rows and undoes exactly them."""

    __tablename__ = "repayment_payment_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "installment_id", name="uq_allocation_payment_installment"),
        CheckConstraint(
            "fee_amount >= 0 AND interest_amount >= 0 AND principal_amount >= 0 "
            "AND fee_amount + interest_amount + principal_amount > 0",
            name="ck_allocation_amounts",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_payments.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    installment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_installments.id", ondelete="RESTRICT"), nullable=False
    )
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    interest_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())


class RepaymentEvent(Base):
    """Every verified provider callback, stored once (duplicate protection)."""

    __tablename__ = "repayment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_repayment_event_provider_event"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_payments.id", ondelete="RESTRICT"), index=True
    )
    reported_status: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
