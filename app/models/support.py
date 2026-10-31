from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


class SupportTicket(Base):
    """A customer's question, issue or complaint (grievance)."""

    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("ticket_number", name="uq_support_ticket_number"),
        CheckConstraint("kind IN ('QUESTION','ISSUE','COMPLAINT')", name="ck_support_ticket_kind"),
        CheckConstraint(
            "category IN ('LOAN_APPLICATION','KYC','DISBURSEMENT','REPAYMENT','CHARGES',"
            "'COLLECTIONS_CONDUCT','FRAUD_OR_UNAUTHORISED','DATA_PRIVACY','OTHER')",
            name="ck_support_ticket_category",
        ),
        CheckConstraint(
            "sensitive = (category IN ('FRAUD_OR_UNAUTHORISED','DATA_PRIVACY'))",
            name="ck_support_ticket_sensitive",
        ),
        CheckConstraint("priority IN ('LOW','NORMAL','HIGH','URGENT')", name="ck_support_ticket_priority"),
        CheckConstraint(
            "status IN ('OPEN','IN_PROGRESS','WAITING_ON_CUSTOMER','RESOLVED','CLOSED')",
            name="ck_support_ticket_status",
        ),
        CheckConstraint(
            "status NOT IN ('RESOLVED','CLOSED') OR resolved_at IS NOT NULL", name="ck_support_ticket_resolved"
        ),
        CheckConstraint("(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_support_ticket_closed"),
        CheckConstraint(
            "(assigned_to_admin_user_id IS NULL) = (assigned_at IS NULL)", name="ck_support_ticket_assignment"
        ),
        CheckConstraint("escalation_level BETWEEN 0 AND 2", name="ck_support_ticket_level"),
        CheckConstraint(
            "kind = 'COMPLAINT' OR escalation_level = 0", name="ck_support_ticket_escalation_complaints_only"
        ),
        CheckConstraint(
            "(kind = 'COMPLAINT') = (sla_due_at IS NOT NULL)", name="ck_support_ticket_sla_complaints_only"
        ),
        Index("ix_support_ticket_user", "user_id", "created_at"),
        Index("ix_support_ticket_status", "status", "created_at"),
        Index("ix_support_ticket_assignee", "assigned_to_admin_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_number: Mapped[str] = mapped_column(String(24), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, default="NORMAL")
    loan_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_applications.id", ondelete="RESTRICT")
    )
    loan_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT")
    )
    assigned_to_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    assigned_at: Mapped[datetime | None] = _ts()
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_due_at: Mapped[datetime | None] = _ts()
    first_response_at: Mapped[datetime | None] = _ts()
    resolved_at: Mapped[datetime | None] = _ts()
    closed_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())


class SupportTicketEvent(Base):
    """The conversation and history of a ticket. Append-only (trigger)."""

    __tablename__ = "support_ticket_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('TICKET_CREATED','CUSTOMER_MESSAGE','AGENT_REPLY','INTERNAL_NOTE','STATUS_CHANGED',"
            "'ASSIGNED','PRIORITY_CHANGED','ESCALATED','CONTACT_REVEALED')",
            name="ck_support_event_type",
        ),
        CheckConstraint("visibility IN ('CUSTOMER','INTERNAL')", name="ck_support_event_visibility"),
        CheckConstraint(
            "event_type IN ('TICKET_CREATED','CUSTOMER_MESSAGE','AGENT_REPLY','STATUS_CHANGED') "
            "OR visibility = 'INTERNAL'",
            name="ck_support_event_internal_kinds",
        ),
        CheckConstraint("actor_type IN ('CUSTOMER','ADMIN','SYSTEM')", name="ck_support_event_actor_type"),
        CheckConstraint(
            "(actor_type = 'ADMIN') = (actor_admin_user_id IS NOT NULL)", name="ck_support_event_actor"
        ),
        Index("ix_support_event_ticket", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    visibility: Mapped[str] = mapped_column(String(8), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(8), nullable=False)
    actor_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
