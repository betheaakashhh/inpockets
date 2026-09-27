from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ( # type: ignore
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
) 
from sqlalchemy.dialects.postgresql import JSONB, UUID # type: ignore
from sqlalchemy.orm import Mapped, mapped_column, relationship # type: ignore

from app.db.base import Base


class FraudAssessment(Base):
    __tablename__ = "fraud_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    loan_application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "loan_applications.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    provider_reference: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    risk_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    signals: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    loan_application = relationship(
        "LoanApplication",
        back_populates="fraud_assessments",
    )

    user = relationship("User")

    __table_args__ = (
    Index(
        "ix_fraud_assessments_loan_application_id",
        "loan_application_id",
    ),
    Index(
        "ix_fraud_assessments_status",
        "status",
    ),
    Index(
        "ix_fraud_assessments_user_id",
        "user_id",
    ),
    UniqueConstraint(
        "provider",
        "provider_reference",
        name="uq_fraud_assessments_provider_reference",
    ),
)