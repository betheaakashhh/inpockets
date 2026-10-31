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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MONEY = Numeric(14, 2)


class ReconciliationRun(Base):
    """One reconciliation of one flow, with one provider, for one Indian
    calendar day. Never deleted; at most one per (flow, provider, day)."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        UniqueConstraint("flow", "provider", "report_date", name="uq_recon_run_day"),
        CheckConstraint("flow IN ('COLLECTION','DISBURSEMENT')", name="ck_recon_run_flow"),
        CheckConstraint("status IN ('RUNNING','COMPLETED','FAILED')", name="ck_recon_run_status"),
        CheckConstraint(
            "(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="ck_recon_run_completed"
        ),
        CheckConstraint(
            "internal_count >= 0 AND external_count >= 0 AND matched_count >= 0 "
            "AND unmatched_count >= 0 AND mismatch_count >= 0 AND review_count >= 0",
            name="ck_recon_run_counts",
        ),
        Index("ix_recon_run_status", "status", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="RUNNING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(String(200))
    internal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mismatch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    triggered_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ReconciliationRecord(Base):
    """One finding for one provider reference in one run.

    The finding columns never change (database trigger); only the review
    columns move, and RESOLVED is final. A finding is never "fixed" by editing
    it: corrections go through the normal repayment/ledger flows."""

    __tablename__ = "reconciliation_records"
    __table_args__ = (
        UniqueConstraint("run_id", "provider_ref", name="uq_recon_record_run_ref"),
        CheckConstraint("flow IN ('COLLECTION','DISBURSEMENT')", name="ck_recon_record_flow"),
        CheckConstraint(
            "status IN ('MATCHED','UNMATCHED','MISMATCH','REQUIRES_REVIEW')",
            name="ck_recon_record_status",
        ),
        CheckConstraint(
            "discrepancy IS NULL OR discrepancy IN ('MISSING_EXTERNAL','MISSING_INTERNAL',"
            "'AMOUNT_MISMATCH','STATUS_MISMATCH','DUPLICATE_EXTERNAL','LEDGER_MISMATCH')",
            name="ck_recon_record_discrepancy",
        ),
        CheckConstraint(
            "(status = 'MATCHED') = (discrepancy IS NULL)", name="ck_recon_record_matched"
        ),
        CheckConstraint(
            "review_status IN ('NOT_REQUIRED','OPEN','IN_REVIEW','RESOLVED')",
            name="ck_recon_record_review_status",
        ),
        CheckConstraint(
            "(status = 'MATCHED') = (review_status = 'NOT_REQUIRED')",
            name="ck_recon_record_review_required",
        ),
        CheckConstraint(
            "review_status <> 'RESOLVED' OR (resolution IS NOT NULL AND review_note IS NOT NULL "
            "AND reviewed_by_admin_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_recon_record_resolved_complete",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('EXPLAINED','CORRECTED_ELSEWHERE',"
            "'ESCALATED_TO_PROVIDER')",
            name="ck_recon_record_resolution",
        ),
        CheckConstraint("external_count >= 0", name="ck_recon_record_external_count"),
        Index("ix_recon_record_run", "run_id"),
        Index("ix_recon_record_internal", "internal_type", "internal_id"),
        Index(
            "ix_recon_record_open",
            "review_status",
            "created_at",
            postgresql_where=text("review_status IN ('OPEN','IN_REVIEW')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    flow: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    discrepancy: Mapped[str | None] = mapped_column(String(24))
    detail: Mapped[str] = mapped_column(String(300), nullable=False)

    # our side (no foreign key: it points at payments or disbursements by type)
    internal_type: Mapped[str | None] = mapped_column(String(24))
    internal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    internal_status: Mapped[str | None] = mapped_column(String(20))
    internal_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    ledger_net: Mapped[Decimal | None] = mapped_column(MONEY)
    expected_ledger_net: Mapped[Decimal | None] = mapped_column(MONEY)

    # the provider's side
    external_line_id: Mapped[str | None] = mapped_column(String(255))
    external_status: Mapped[str | None] = mapped_column(String(20))
    external_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    external_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # review workflow
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    resolution: Mapped[str | None] = mapped_column(String(24))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
