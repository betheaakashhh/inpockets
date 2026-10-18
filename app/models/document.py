import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
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
    CheckConstraint(
        """
        (
            loan_offer_id IS NULL
            AND loan_offer_version IS NULL
            AND template_key IS NULL
            AND template_version IS NULL
        )
        OR
        (
            loan_offer_id IS NOT NULL
            AND loan_offer_version IS NOT NULL
            AND loan_offer_version >= 1
            AND template_key IS NOT NULL
            AND length(trim(template_key)) > 0
            AND template_version IS NOT NULL
            AND length(trim(template_version)) > 0
        )
        """,
        name="ck_documents_offer_provenance_complete",
    ),
    CheckConstraint(
        "loan_offer_id IS NULL OR is_immutable",
        name="ck_documents_offer_documents_immutable",
    ),
    Index(
        "ix_documents_loan_offer_id_version",
        "loan_offer_id",
        "loan_offer_version",
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
    loan_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "loan_offers.id",
            name="fk_documents_loan_offer_id_loan_offers",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    loan_offer_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    template_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    template_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
