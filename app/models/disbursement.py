from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
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


class Disbursement(Base):
    """One payout attempt for an accepted, e-signed offer.

    The idempotency key is sent to the provider on every submit for this row,
    so repeating the call can never pay twice. The account number is not
    stored here: only the bank verification it was bound to, plus last four.
    """

    __tablename__ = "disbursements"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_disbursement_idempotency_key"),
        UniqueConstraint("provider", "provider_ref", name="uq_disbursement_provider_ref"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCESS','FAILED','REVERSED','REQUIRES_REVIEW')",
            name="ck_disbursement_status",
        ),
        CheckConstraint("amount > 0", name="ck_disbursement_amount_positive"),
        CheckConstraint(
            "status NOT IN ('SUCCESS','REVERSED') OR provider_ref IS NOT NULL",
            name="ck_disbursement_provider_ref_when_paid",
        ),
        CheckConstraint(
            "(status IN ('SUCCESS','REVERSED')) = (completed_at IS NOT NULL)",
            name="ck_disbursement_completed_iff_paid",
        ),
        CheckConstraint(
            "(status = 'REVERSED') = (reversed_at IS NOT NULL)",
            name="ck_disbursement_reversed_at_iff_reversed",
        ),
        CheckConstraint("attempt >= 1", name="ck_disbursement_attempt"),
        CheckConstraint("beneficiary_last4 ~ '^[0-9]{4}$'", name="ck_disbursement_last4"),
        Index("ix_disbursement_status_requested", "status", "requested_at"),
        Index("ix_disbursement_offer", "loan_offer_id"),
        Index("ix_disbursement_user", "user_id"),
        # One live disbursement per offer: concurrent duplicates cannot both exist.
        Index(
            "uq_disbursement_one_live_per_offer",
            "loan_offer_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING','PROCESSING','SUCCESS','REQUIRES_REVIEW')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    loan_application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_applications.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    esign_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("esign_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    bank_verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bank_account_verifications.id", ondelete="RESTRICT"),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    beneficiary_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    beneficiary_ifsc: Mapped[str] = mapped_column(String(11), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disbursements.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    utr: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(50))
    review_reason: Mapped[str | None] = mapped_column(String(100))
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    requested_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DisbursementEvent(Base):
    """Every verified provider callback, stored once (duplicate protection)."""

    __tablename__ = "disbursement_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_disbursement_event_provider_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    disbursement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("disbursements.id", ondelete="RESTRICT"), index=True
    )
    reported_status: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
