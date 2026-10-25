from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LateChargeAssessment(Base):
    """One day's late/bounce charge on one installment. Append-only (trigger);
    at most one row per installment per day, so re-running the job is safe."""

    __tablename__ = "late_charge_assessments"
    __table_args__ = (
        UniqueConstraint("installment_id", "charge_date", name="uq_late_charge_installment_day"),
        CheckConstraint("kind IN ('BOUNCE','PENAL')", name="ck_late_charge_kind"),
        CheckConstraint("amount > 0 AND basis_amount > 0", name="ck_late_charge_positive"),
        Index("ix_late_charge_schedule", "schedule_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_installments.id", ondelete="RESTRICT"), nullable=False
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    charge_date: Mapped[date] = mapped_column(Date, nullable=False)
    basis_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
