"""create risk assessments table

Revision ID: 7d1f6b2a9c40
Revises: 58fabdfb3011
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7d1f6b2a9c40"
down_revision: Union[str, Sequence[str], None] = "58fabdfb3011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("loan_application_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("risk_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("risk_band", sa.String(length=50), nullable=False),
        sa.Column("recommended_action", sa.String(length=50), nullable=False),
        sa.Column("recommended_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("max_eligible_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "factors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["loan_application_id"],
            ["loan_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_risk_assessments_loan_application_id",
        "risk_assessments",
        ["loan_application_id"],
        unique=False,
    )
    op.create_index(
        "ix_risk_assessments_user_id",
        "risk_assessments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_risk_assessments_status",
        "risk_assessments",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_risk_assessments_created_at",
        "risk_assessments",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_assessments_created_at",
        table_name="risk_assessments",
    )
    op.drop_index(
        "ix_risk_assessments_status",
        table_name="risk_assessments",
    )
    op.drop_index(
        "ix_risk_assessments_user_id",
        table_name="risk_assessments",
    )
    op.drop_index(
        "ix_risk_assessments_loan_application_id",
        table_name="risk_assessments",
    )
    op.drop_table("risk_assessments")
