import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    """Generic, object-storage-backed document reference. The actual bytes
    live in storage via the DocumentStorage provider - this row is metadata
    plus a pointer (storage_ref), never the content itself.

    owner_type/owner_id is a deliberately loose polymorphic association (a
    document belongs to a user during KYC, later to a loan for an agreement,
    etc.) rather than a hard foreign key - there's no DB-level referential
    integrity on ownership, which is fine here because a document's real
    lookup path is always through the owning row (e.g. kyc_documents), not
    this column.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    owner_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    storage_ref: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

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
