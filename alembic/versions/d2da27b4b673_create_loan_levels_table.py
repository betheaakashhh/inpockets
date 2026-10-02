"""create loan levels table

Revision ID: d2da27b4b673
Revises: dae4ca57b932
Create Date: 2026-09-29 02:43:32.469377

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2da27b4b673"
down_revision: Union[str, Sequence[str], None] = "dae4ca57b932"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "loan_levels",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "code",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=150),
            nullable=False,
        ),
        sa.Column(
            "min_amount",
            sa.Numeric(14, 2),
            nullable=False,
        ),
        sa.Column(
            "max_amount",
            sa.Numeric(14, 2),
            nullable=False,
        ),
        sa.Column(
            "min_tenure_days",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "max_tenure_days",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code",
            name="uq_loan_levels_code",
        ),
    )

    op.create_index(
        "ix_loan_levels_code",
        "loan_levels",
        ["code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_loan_levels_code",
        table_name="loan_levels",
    )

    op.drop_table("loan_levels")