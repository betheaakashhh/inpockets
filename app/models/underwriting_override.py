from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnderwritingOverride(Base):
    __tablename__ = "underwriting_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    review_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "underwriting_review_cases.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    requested_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    override_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    original_value: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )

    requested_value: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="REQUESTED",
    )

    approved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_underwriting_overrides_case_created",
            "review_case_id",
            "created_at",
        ),
        Index(
            "ix_underwriting_overrides_case_status",
            "review_case_id",
            "status",
        ),
        Index(
            "ix_underwriting_overrides_requested_by_created",
            "requested_by_admin_user_id",
            "created_at",
        ),
    )