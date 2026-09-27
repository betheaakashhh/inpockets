import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ( # type: ignore
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
) 
from sqlalchemy.dialects.postgresql import JSONB, UUID #type: ignore 
from sqlalchemy.orm import Mapped, mapped_column, relationship # type: ignore

from app.db.base import Base


class CreditAssessment(Base):
    __tablename__ = "credit_assessments"

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
    
    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("consents.id", ondelete="RESTRICT"),
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

    bureau_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    score_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    total_accounts: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    active_accounts: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    delinquent_accounts: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    total_outstanding: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )

    recent_inquiries: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    feature_snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    provider_report_version: Mapped[str | None] = mapped_column(
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
        back_populates="credit_assessments",
    )

    user = relationship("User")

    __table_args__ = (
        Index(
            "ix_credit_assessments_loan_application_id",
            "loan_application_id",
        ),
        Index(
            "ix_credit_assessments_user_id",
            "user_id",
        ),
        Index(
            "ix_credit_assessments_status",
            "status",
        ),
         UniqueConstraint(
            "provider",
            "provider_reference",
            name="uq_credit_assessments_provider_reference",
        ),
    )