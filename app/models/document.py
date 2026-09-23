import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    """Metadata for a document whose bytes live in object storage."""

    __tablename__ = "documents"
    __table_args__ = (
    UniqueConstraint(
        "owner_type",
        "owner_id",
        "checksum",
        name="uq_documents_owner_checksum",
    ),
    UniqueConstraint(
        "storage_ref",
        name="uq_documents_storage_ref",
    ),
    UniqueConstraint(
        "document_family_id",
        "version",
        name="uq_documents_family_version",
    ),
)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_type: Mapped[str] = mapped_column(String(50), nullable=False)

    owner_type: Mapped[str] = mapped_column(String(50), nullable=False)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    document_family_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    nullable=False,
    index=True,
    )

    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)

    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    content_type: Mapped[str] = mapped_column(String(100), nullable=False)

    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    is_immutable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
