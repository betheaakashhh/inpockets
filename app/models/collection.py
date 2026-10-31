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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MONEY = Numeric(14, 2)


class CollectionCase(Base):
    """One overdue loan being worked. At most one live (not CLOSED) case per
    repayment schedule; a closed case is final and a later default opens a
    new one."""

    __tablename__ = "collection_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','ESCALATED','CLOSED')", name="ck_collection_case_status"
        ),
        CheckConstraint(
            "status = 'CLOSED' OR dpd >= 1", name="ck_collection_case_open_is_overdue"
        ),
        CheckConstraint("dpd >= 0", name="ck_collection_case_dpd"),
        CheckConstraint(
            "overdue_principal >= 0 AND overdue_interest >= 0 AND overdue_fees >= 0",
            name="ck_collection_case_amounts",
        ),
        CheckConstraint("escalation_level BETWEEN 0 AND 3", name="ck_collection_case_level"),
        CheckConstraint(
            "status = 'CLOSED' OR (status = 'ESCALATED') = (escalation_level > 0)",
            name="ck_collection_case_escalated_iff_level",
        ),
        CheckConstraint(
            "(status = 'CLOSED') = (closed_at IS NOT NULL) AND "
            "(status = 'CLOSED') = (close_reason IS NOT NULL)",
            name="ck_collection_case_closed",
        ),
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('CURED','LOAN_INACTIVE')",
            name="ck_collection_case_close_reason",
        ),
        CheckConstraint(
            "(assigned_to_admin_user_id IS NULL) = (assigned_at IS NULL)",
            name="ck_collection_case_assignment",
        ),
        CheckConstraint(
            "next_action IS NULL OR next_action IN ('CALL','SEND_REMINDER','FOLLOW_UP','ESCALATION_REVIEW')",
            name="ck_collection_case_next_action",
        ),
        Index("ix_collection_case_status_dpd", "status", "dpd"),
        Index("ix_collection_case_assignee", "assigned_to_admin_user_id"),
        Index("ix_collection_case_user", "user_id"),
        Index(
            "uq_collection_case_one_live_per_schedule",
            "schedule_id",
            unique=True,
            postgresql_where=text("status <> 'CLOSED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    # the oldest installment still overdue (moves as older ones are paid)
    oldest_installment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_installments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="OPEN")
    dpd: Mapped[int] = mapped_column(Integer, nullable=False)
    dpd_bucket: Mapped[str | None] = mapped_column(String(8))
    overdue_principal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    overdue_interest: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    overdue_fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_to_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action: Mapped[str | None] = mapped_column(String(20))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(16))
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CollectionEvent(Base):
    """The case history. Append-only (database trigger). A reminder or
    escalation carries a dedupe key, unique per case, so the same one can
    never be created twice however often the workers run."""

    __tablename__ = "collection_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('CASE_OPENED','BUCKET_CHANGED','ASSIGNED','NOTE_ADDED','CONTACT_ATTEMPT',"
            "'NEXT_ACTION_SET','REMINDER_SCHEDULED','ESCALATED','CASE_CLOSED')",
            name="ck_collection_event_type",
        ),
        CheckConstraint("actor_type IN ('SYSTEM','ADMIN')", name="ck_collection_event_actor_type"),
        CheckConstraint(
            "(actor_type = 'ADMIN') = (actor_admin_user_id IS NOT NULL)",
            name="ck_collection_event_actor",
        ),
        CheckConstraint(
            "channel IS NULL OR channel IN ('SMS','PUSH','EMAIL','CALL','WHATSAPP')",
            name="ck_collection_event_channel",
        ),
        CheckConstraint(
            "event_type <> 'REMINDER_SCHEDULED' OR (channel IS NOT NULL AND dedupe_key IS NOT NULL "
            "AND template_key IS NOT NULL)",
            name="ck_collection_event_reminder_complete",
        ),
        Index("ix_collection_event_case", "case_id", "created_at"),
        Index(
            "uq_collection_event_dedupe",
            "case_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_cases.id", ondelete="RESTRICT"), nullable=False
    )
    installment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repayment_installments.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(8), nullable=False)
    actor_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[str | None] = mapped_column(String(10))
    template_key: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
