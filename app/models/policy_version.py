import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    version: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    rules: Mapped[list["PolicyRule"]] = relationship(
        "PolicyRule",
        back_populates="policy_version",
        cascade="all, delete-orphan",
        order_by="PolicyRule.rule_order.asc()",
    )

    evaluations: Mapped[list["PolicyEvaluation"]] = relationship(
    "PolicyEvaluation",
    back_populates="policy_version_record",
    )

    __table_args__ = (
        Index(
            "ix_policy_versions_effective_from",
            "effective_from",
        ),
        Index(
            "ix_policy_versions_effective_to",
            "effective_to",
        ),
    )