from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BankAccountVerification(Base):
    """One bank-account verification attempt.

    Minimum bank metadata only: the account number exists solely as AES-GCM
    ciphertext; the clear columns are last four digits, IFSC (a public branch
    code), a keyed fingerprint for duplicate detection, and the bank name.
    """

    __tablename__ = "bank_account_verifications"
    __table_args__ = (
        UniqueConstraint("provider", "provider_ref", name="uq_bank_verif_provider_ref"),
        CheckConstraint(
            "status IN ('INITIATED','PENDING','VERIFIED','FAILED','MANUAL_REVIEW')",
            name="ck_bank_verif_status",
        ),
        CheckConstraint(
            "status NOT IN ('PENDING','VERIFIED') OR provider_ref IS NOT NULL",
            name="ck_bank_verif_provider_ref_when_active",
        ),
        CheckConstraint(
            "(status = 'VERIFIED') = (verified_at IS NOT NULL)",
            name="ck_bank_verif_verified_at_iff_verified",
        ),
        CheckConstraint("account_last4 ~ '^[0-9]{4}$'", name="ck_bank_verif_last4"),
        CheckConstraint("ifsc ~ '^[A-Z]{4}0[A-Z0-9]{6}$'", name="ck_bank_verif_ifsc"),
        CheckConstraint(
            "length(account_fingerprint) = 64", name="ck_bank_verif_fingerprint_len"
        ),
        CheckConstraint(
            "(reviewed_by_admin_user_id IS NULL) = (reviewed_at IS NULL)",
            name="ck_bank_verif_review_pair",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR status = 'VERIFIED'",
            name="ck_bank_verif_superseded_only_verified",
        ),
        Index("ix_bank_verif_user_requested", "user_id", "requested_at"),
        Index("ix_bank_verif_fingerprint", "account_fingerprint"),
        Index("ix_bank_verif_status_expires", "status", "expires_at"),
        # One in-flight verification per user.
        Index(
            "uq_bank_verif_one_in_flight_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('INITIATED','PENDING','MANUAL_REVIEW')"),
        ),
        # One current verified account per user.
        Index(
            "uq_bank_verif_one_current_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'VERIFIED' AND superseded_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="INITIATED")

    # Sensitive: ciphertext only (see app.core.encryption).
    account_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(50), nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    account_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(100))

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    client_reference: Mapped[str] = mapped_column(String(128), nullable=False)

    name_match_result: Mapped[str | None] = mapped_column(String(20))
    failure_code: Mapped[str | None] = mapped_column(String(50))
    resolution_reason: Mapped[str | None] = mapped_column(String(500))
    reviewed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requested_at: Mapped[datetime] = mapped_column(
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

    def __repr__(self) -> str:  # never include ciphertext or account data
        return f"<BankAccountVerification id={self.id} status={self.status}>"
