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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LoanOffer(Base):
    """A versioned loan offer with immutable issued commercial terms."""

    __tablename__ = "loan_offers"

    __table_args__ = (
        UniqueConstraint(
            "loan_application_id",
            "version",
            name="uq_loan_offers_application_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_loan_offers_version_positive",
        ),
        CheckConstraint(
            "principal_amount > 0",
            name="ck_loan_offers_principal_positive",
        ),
        CheckConstraint(
            "tenure_days > 0",
            name="ck_loan_offers_tenure_positive",
        ),
        CheckConstraint(
            "expires_at IS NULL OR issued_at IS NOT NULL",
            name="ck_loan_offers_expiry_requires_issue",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > issued_at",
            name="ck_loan_offers_expiry_after_issue",
        ),
        CheckConstraint(
            """
            (status = 'DRAFT' AND issued_at IS NULL AND expires_at IS NULL)
            OR
            (status <> 'DRAFT' AND issued_at IS NOT NULL AND expires_at IS NOT NULL)
            """,
            name="ck_loan_offers_status_issue_timestamps",
        ),
        CheckConstraint(
            """
            (status = 'ACCEPTED' AND accepted_at IS NOT NULL)
            OR
            (status <> 'ACCEPTED' AND accepted_at IS NULL)
            """,
            name="ck_loan_offers_acceptance_timestamp",
        ),
        CheckConstraint(
        """
        status <> 'ACCEPTED'
        OR (
        accepted_at >= issued_at
        AND accepted_at < expires_at
        )
        """,

    name="ck_loan_offers_acceptance_window",
),
        Index(
            "ix_loan_offers_user_status",
            "user_id",
            "status",
        ),
        Index(
            "ix_loan_offers_application_status",
            "loan_application_id",
            "status",
        ),
        Index(
            "ix_loan_offers_expiry",
            "expires_at",
        ),
        Index(
            "uq_loan_offers_one_open_per_application",
            "loan_application_id",
            unique=True,
            postgresql_where=text("status IN ('ISSUED', 'ACCEPTED')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    loan_application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    principal_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    tenure_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    commercial_terms: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="DRAFT",
        server_default="DRAFT",
        index=True,
    )

    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # References to the exact generated documents for this offer version.
    kfs_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=True,
    )

    agreement_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=True,
    )

    created_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
