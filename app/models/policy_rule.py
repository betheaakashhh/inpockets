import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    rule_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    effect: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    condition: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    reason_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    policy_version: Mapped["PolicyVersion"] = relationship(
        "PolicyVersion",
        back_populates="rules",
    )

    __table_args__ = (
    Index("ix_policy_rules_policy_version_id", "policy_version_id"),
    Index(
        "ix_policy_rules_policy_version_order",
        "policy_version_id",
        "rule_order",
    ),
    UniqueConstraint(
        "policy_version_id",
        "code",
        name="uq_policy_rules_policy_version_code",
    ),
    UniqueConstraint(
        "policy_version_id",
        "rule_order",
        name="uq_policy_rules_policy_version_order",
    ),
)