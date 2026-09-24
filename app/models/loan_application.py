import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ( #type: ignore
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID #type: ignore
from sqlalchemy.orm import Mapped, mapped_column, relationship #type: ignore

from app.db.base import Base
from app.domain.loan_application import LoanApplicationStatus


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    application_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[LoanApplicationStatus] = mapped_column(
        String(50),
        nullable=False,
        default=LoanApplicationStatus.DRAFT,
    )

    requested_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    requested_tenure_days: Mapped[int] = mapped_column(
        nullable=False,
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    events: Mapped[list["LoanApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="LoanApplicationEvent.created_at",
    )

    __table_args__ = (
        Index("ix_loan_applications_user_id", "user_id"),
        Index("ix_loan_applications_status", "status"),
        Index("ix_loan_applications_created_at", "created_at"),
    )


class LoanApplicationEvent(Base):
    __tablename__ = "loan_application_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    previous_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    new_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    event_metadata: Mapped[dict | None] = mapped_column(
    JSONB,
    nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    application: Mapped["LoanApplication"] = relationship(
        back_populates="events",
    )

    __table_args__ = (
        Index(
            "ix_loan_application_events_application_id",
            "application_id",
        ),
        Index(
            "ix_loan_application_events_created_at",
            "created_at",
        ),
    )