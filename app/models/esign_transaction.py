from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ESignTransaction(Base):
    """One signing attempt for the exact agreement document of an offer."""

    __tablename__ = "esign_transactions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_ref", name="uq_esign_provider_ref"),
        CheckConstraint(
            "status IN ('INITIATED','PENDING','SIGNED','FAILED','EXPIRED','MANUAL_REVIEW')",
            name="ck_esign_status",
        ),
        CheckConstraint(
            "status NOT IN ('PENDING','SIGNED') OR provider_ref IS NOT NULL",
            name="ck_esign_provider_ref_when_active",
        ),
        CheckConstraint(
            "(status = 'SIGNED') = (signed_at IS NOT NULL)",
            name="ck_esign_signed_at_iff_signed",
        ),
        CheckConstraint(
            "(reviewed_by_admin_user_id IS NULL) = (reviewed_at IS NULL)",
            name="ck_esign_review_pair",
        ),
        CheckConstraint("loan_offer_version >= 1", name="ck_esign_offer_version"),
        CheckConstraint("length(document_checksum) = 64", name="ck_esign_checksum_len"),
        Index("ix_esign_user_status", "user_id", "status"),
        Index("ix_esign_status_expires", "status", "expires_at"),
        Index(
            "uq_esign_one_live_per_offer",
            "loan_offer_id",
            unique=True,
            postgresql_where=text(
                "status IN ('INITIATED','PENDING','SIGNED','MANUAL_REVIEW')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_offers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    loan_offer_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # The exact document (and bytes) sent for signing.
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    # Idempotency reference we send to the provider; same value on every retry.
    client_reference: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="INITIATED")
    failure_reason: Mapped[str | None] = mapped_column(String(255))

    signed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT")
    )
    signed_checksum: Mapped[str | None] = mapped_column(String(64))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Manual-review resolution (admin workflow).
    reviewed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_reason: Mapped[str | None] = mapped_column(String(500))

    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
