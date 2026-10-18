
"""add loan offer document provenance

Revision ID: a7114ea9db2e
Revises: d05088670dc1
Create Date: 2026-10-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7114ea9db2e"
down_revision: Union[str, Sequence[str], None] = "d05088670dc1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add provenance metadata for generated loan-offer documents."""

    op.add_column(
        "documents",
        sa.Column("loan_offer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("loan_offer_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("template_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("template_version", sa.String(length=50), nullable=True),
    )

    op.create_foreign_key(
        "fk_documents_loan_offer_id_loan_offers",
        "documents",
        "loan_offers",
        ["loan_offer_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_documents_offer_provenance_complete",
        "documents",
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
    )

    op.create_index(
        "ix_documents_loan_offer_id_version",
        "documents",
        ["loan_offer_id", "loan_offer_version"],
        unique=False,
    )


def downgrade() -> None:
    """Remove loan-offer document provenance metadata."""

    op.drop_index(
        "ix_documents_loan_offer_id_version",
        table_name="documents",
    )
    op.drop_constraint(
        "ck_documents_offer_provenance_complete",
        "documents",
        type_="check",
    )
    op.drop_constraint(
        "fk_documents_loan_offer_id_loan_offers",
        "documents",
        type_="foreignkey",
    )

    op.drop_column("documents", "template_version")
    op.drop_column("documents", "template_key")
    op.drop_column("documents", "loan_offer_version")
    op.drop_column("documents", "loan_offer_id")
