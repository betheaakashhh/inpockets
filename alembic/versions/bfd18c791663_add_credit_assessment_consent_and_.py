"""add credit assessment consent and provider uniqueness

Revision ID: bfd18c791663
Revises: 8231b23b193d
Create Date: 2026-09-26 03:49:59.980263

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfd18c791663'
down_revision: Union[str, Sequence[str], None] = '8231b23b193d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "credit_assessments",
        sa.Column("consent_id", sa.UUID(), nullable=False),
    )

    op.create_foreign_key(
        "fk_credit_assessments_consent_id_consents",
        "credit_assessments",
        "consents",
        ["consent_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_unique_constraint(
        "uq_credit_assessments_provider_reference",
        "credit_assessments",
        ["provider", "provider_reference"],
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_credit_assessments_provider_reference",
        "credit_assessments",
        type_="unique",
    )

    op.drop_constraint(
        "fk_credit_assessments_consent_id_consents",
        "credit_assessments",
        type_="foreignkey",
    )

    op.drop_column(
        "credit_assessments",
        "consent_id",
    )
