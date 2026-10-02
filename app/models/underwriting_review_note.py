from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnderwritingReviewNote(Base):
    __tablename__ = "underwriting_review_notes"

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
        index=True,
    )

    author_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_underwriting_review_notes_case_created",
            "review_case_id",
            "created_at",
        ),
        Index(
            "ix_underwriting_review_notes_author_created",
            "author_admin_user_id",
            "created_at",
        ),
    )