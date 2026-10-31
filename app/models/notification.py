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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _ts(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


class NotificationTemplate(Base):
    """A versioned message template. Content is frozen once created (database
    trigger); only DRAFT -> APPROVED/REJECTED can happen, and the approver must
    be a different admin than the author."""

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("template_key", "channel", "locale", "version", name="uq_notification_template_version"),
        CheckConstraint("channel IN ('SMS','PUSH','EMAIL')", name="ck_notification_template_channel"),
        CheckConstraint(
            "category IN ('TRANSACTIONAL','SERVICE','COLLECTIONS','MARKETING')",
            name="ck_notification_template_category",
        ),
        CheckConstraint("status IN ('DRAFT','APPROVED','REJECTED')", name="ck_notification_template_status"),
        CheckConstraint("version >= 1", name="ck_notification_template_version"),
        CheckConstraint(
            "(status = 'APPROVED') = (approved_at IS NOT NULL)", name="ck_notification_template_approved_at"
        ),
        CheckConstraint(
            "approved_by_admin_user_id IS NULL OR approved_by_admin_user_id <> created_by_admin_user_id",
            name="ck_notification_template_maker_checker",
        ),
        CheckConstraint(
            "(channel = 'EMAIL') = (subject IS NOT NULL)", name="ck_notification_template_subject"
        ),
        Index("ix_notification_template_lookup", "template_key", "channel", "status", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_variables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="DRAFT")
    created_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    approved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())


class Notification(Base):
    """One message to one customer on one channel. Holds no message text and
    no phone number: only which template version and the few variables."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("channel IN ('SMS','PUSH','EMAIL')", name="ck_notification_channel"),
        CheckConstraint(
            "category IN ('TRANSACTIONAL','SERVICE','COLLECTIONS','MARKETING')", name="ck_notification_category"
        ),
        CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','DELIVERED','DELIVERY_FAILED','DEAD','SUPPRESSED')",
            name="ck_notification_status",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="ck_notification_attempts"),
        CheckConstraint(
            "(status = 'SUPPRESSED') = (suppress_reason IS NOT NULL)", name="ck_notification_suppressed"
        ),
        CheckConstraint("(status = 'DEAD') = (dead_at IS NOT NULL)", name="ck_notification_dead"),
        CheckConstraint(
            "status NOT IN ('SENT','DELIVERED','DELIVERY_FAILED') OR provider_ref IS NOT NULL",
            name="ck_notification_provider_ref_when_sent",
        ),
        CheckConstraint(
            "status IN ('SUPPRESSED') OR template_version IS NOT NULL", name="ck_notification_template_known"
        ),
        UniqueConstraint("dedupe_key", name="uq_notification_dedupe_key"),
        Index("ix_notification_due", "status", "next_attempt_at"),
        Index("ix_notification_user", "user_id", "created_at"),
        Index(
            "uq_notification_provider_ref",
            "provider",
            "provider_ref",
            unique=True,
            postgresql_where=text("provider_ref IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    template_version: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    locked_at: Mapped[datetime | None] = _ts()
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    failure_code: Mapped[str | None] = mapped_column(String(50))
    suppress_reason: Mapped[str | None] = mapped_column(String(30))
    sent_at: Mapped[datetime | None] = _ts()
    delivered_at: Mapped[datetime | None] = _ts()
    dead_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())


class NotificationAttempt(Base):
    """Every send attempt and how it ended. Append-only."""

    __tablename__ = "notification_attempts"
    __table_args__ = (
        UniqueConstraint("notification_id", "attempt_no", "outcome", name="uq_notification_attempt"),
        CheckConstraint(
            "outcome IN ('SENT','TRANSIENT_FAILURE','PERMANENT_FAILURE','REQUEUED','LEASE_EXPIRED')",
            name="ck_notification_attempt_outcome",
        ),
        Index("ix_notification_attempt_notification", "notification_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(50))
    actor_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())


class NotificationEvent(Base):
    """Every verified provider delivery receipt, stored once (duplicate protection)."""

    __tablename__ = "notification_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_notification_event_provider_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="RESTRICT"), index=True
    )
    reported_status: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, default="RECEIVED")
    received_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())


class NotificationPreference(Base):
    """A customer's choice for one category on one channel. Transactional
    messages cannot be switched off, so they have no preference row."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "channel", name="uq_notification_preference"),
        CheckConstraint("category IN ('SERVICE','COLLECTIONS','MARKETING')", name="ck_notification_pref_category"),
        CheckConstraint("channel IN ('SMS','PUSH','EMAIL')", name="ck_notification_pref_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(), onupdate=func.now())
