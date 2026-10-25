from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PricingVersion(Base):
    """One admin-configured price list. Maker-checker: the creator can never
    approve. Once decided (APPROVED/REJECTED) it can never change (trigger)."""

    __tablename__ = "pricing_versions"
    __table_args__ = (
        UniqueConstraint("version", name="uq_pricing_version_number"),
        CheckConstraint("status IN ('DRAFT','APPROVED','REJECTED')", name="ck_pricing_status"),
        CheckConstraint(
            "annual_interest_percent >= 0 AND annual_interest_percent <= 100",
            name="ck_pricing_interest_range",
        ),
        CheckConstraint(
            "processing_fee_percent >= 0 AND processing_fee_percent <= 25",
            name="ck_pricing_fee_range",
        ),
        CheckConstraint("gst_percent >= 0 AND gst_percent <= 50", name="ck_pricing_gst_range"),
        CheckConstraint(
            "bounce_percent >= 0 AND bounce_percent <= 100 AND bounce_cap_amount >= 0 "
            "AND penal_annual_percent >= 0 AND penal_annual_percent <= 100 "
            "AND late_total_cap_percent_of_due > 0 AND late_total_cap_percent_of_due <= 100 "
            "AND penal_max_days >= 1",
            name="ck_pricing_late_ranges",
        ),
        CheckConstraint(
            "(status = 'APPROVED') = (approved_by_admin_user_id IS NOT NULL)",
            name="ck_pricing_approver_set",
        ),
        CheckConstraint(
            "(status = 'DRAFT') = (decided_at IS NULL)", name="ck_pricing_decided_at"
        ),
        CheckConstraint(
            "(status = 'REJECTED') = (reject_reason IS NOT NULL)", name="ck_pricing_reject_reason"
        ),
        CheckConstraint(
            "approved_by_admin_user_id IS NULL "
            "OR approved_by_admin_user_id <> created_by_admin_user_id",
            name="ck_pricing_maker_checker",
        ),
        Index("ix_pricing_effective", "status", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    annual_interest_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    processing_fee_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)

    # Late / bounce charges (KreditBee format). OFF until the lender approves.
    late_charges_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bounce_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    bounce_cap_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    penal_annual_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    penal_max_days: Mapped[int] = mapped_column(Integer, nullable=False)
    late_total_cap_percent_of_due: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LoanOfferPricing(Base):
    """The exact price an offer was issued at, frozen when the draft is made.
    Later pricing changes never touch it (no UPDATE/DELETE: trigger)."""

    __tablename__ = "loan_offer_pricing"
    __table_args__ = (
        UniqueConstraint("loan_offer_id", name="uq_offer_pricing_offer"),
        CheckConstraint(
            "net_payout > 0 AND net_payout = principal - processing_fee - gst_amount",
            name="ck_offer_pricing_net",
        ),
        CheckConstraint(
            "total_repayable = principal + total_interest", name="ck_offer_pricing_total"
        ),
        CheckConstraint("months >= 1 AND tenure_days = months * 30", name="ck_offer_pricing_months"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    pricing_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pricing_versions.id", ondelete="RESTRICT"), nullable=False
    )
    principal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tenure_days: Mapped[int] = mapped_column(Integer, nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_interest_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    processing_fee_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    processing_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    net_payout: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    emi_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_interest: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_repayable: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    apr_percent: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    # Late-charge terms copied from the version (used in the next stage).
    late_charges_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    bounce_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    bounce_cap_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    penal_annual_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    penal_max_days: Mapped[int] = mapped_column(Integer, nullable=False)
    late_total_cap_percent_of_due: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
