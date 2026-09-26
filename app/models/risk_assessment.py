import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    loan_application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    model_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    risk_band: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    recommended_action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    recommended_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )

    max_eligible_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )

    factors: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    flags: Mapped[list | None] = mapped_column(
        JSONB,
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
    )

    user = relationship(
        "User",
    )

    __table_args__ = (
        Index(
            "ix_risk_assessments_loan_application_id",
            "loan_application_id",
        ),
        Index(
            "ix_risk_assessments_user_id",
            "user_id",
        ),
        Index(
            "ix_risk_assessments_status",
            "status",
        ),
        Index(
            "ix_risk_assessments_created_at",
            "created_at",
        ),
    )