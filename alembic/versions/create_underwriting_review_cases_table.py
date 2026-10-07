"""create underwriting review cases table

Revision ID: 4c7e91a2d5f0
Revises: b60a4d32d666
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4c7e91a2d5f0"
down_revision: Union[str, Sequence[str], None] = "b60a4d32d666"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "underwriting_review_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "loan_application_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "loan_decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column(
            "assigned_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
        sa.ForeignKeyConstraint(
            ["loan_decision_id"],
            ["loan_decisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_admin_user_id"],
            ["admin_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_underwriting_review_cases_loan_application_id",
        "underwriting_review_cases",
        ["loan_application_id"],
    )

    op.create_index(
        "ix_underwriting_review_cases_user_id",
        "underwriting_review_cases",
        ["user_id"],
    )

    op.create_index(
        "ix_underwriting_review_cases_loan_decision_id",
        "underwriting_review_cases",
        ["loan_decision_id"],
    )

    op.create_index(
        "ix_underwriting_review_cases_status",
        "underwriting_review_cases",
        ["status"],
    )

    op.create_index(
        "ix_underwriting_review_cases_assigned_admin_user_id",
        "underwriting_review_cases",
        ["assigned_admin_user_id"],
    )

    op.create_index(
        "ix_underwriting_review_cases_application_status",
        "underwriting_review_cases",
        ["loan_application_id", "status"],
    )

    op.create_index(
        "ix_underwriting_review_cases_assigned_status",
        "underwriting_review_cases",
        ["assigned_admin_user_id", "status"],
    )

    op.create_index(
        "ix_underwriting_review_cases_user_status",
        "underwriting_review_cases",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_underwriting_review_cases_user_status",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_assigned_status",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_application_status",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_assigned_admin_user_id",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_status",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_loan_decision_id",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_user_id",
        table_name="underwriting_review_cases",
    )
    op.drop_index(
        "ix_underwriting_review_cases_loan_application_id",
        table_name="underwriting_review_cases",
    )
    op.drop_table("underwriting_review_cases")