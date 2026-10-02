from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnderwritingReviewEvidence(Base):
    __tablename__ = "underwriting_review_evidence"

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

    added_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    evidence_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    reference: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    evidence_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_underwriting_review_evidence_case_created",
            "review_case_id",
            "created_at",
        ),
        Index(
            "ix_underwriting_review_evidence_type",
            "evidence_type",
        ),
    )