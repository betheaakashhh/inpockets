import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PolicyEvaluation(Base):
    __tablename__ = "policy_evaluations"

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

    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    policy_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    decision_route: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    matched_rule_codes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    reasons: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    input_snapshot: Mapped[dict] = mapped_column(
        JSONB,
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

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    loan_application = relationship(
        "LoanApplication",
        back_populates="policy_evaluations",
    )

    user = relationship(
        "User",
    )

    policy_version_record = relationship(
        "PolicyVersion",
        back_populates="evaluations",
    )

    __table_args__ = (
        Index(
            "ix_policy_evaluations_loan_application_id",
            "loan_application_id",
        ),
        Index(
            "ix_policy_evaluations_user_id",
            "user_id",
        ),
        Index(
            "ix_policy_evaluations_policy_version_id",
            "policy_version_id",
        ),
        Index(
            "ix_policy_evaluations_decision_route",
            "decision_route",
        ),
        Index(
            "ix_policy_evaluations_evaluated_at",
            "evaluated_at",
        ),
    )