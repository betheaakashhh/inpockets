import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PANVerification(Base):
    """Persisted PAN verification result with the PAN itself masked."""

    __tablename__ = "pan_verifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pan_number_masked: Mapped[str] = mapped_column(String(10), nullable=False)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )

    verified_name: Mapped[str | None] = mapped_column(String(200))

    name_match_result: Mapped[str | None] = mapped_column(String(30))

    failure_reason: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
