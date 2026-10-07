"""create underwriting overrides table

Revision ID: d0e20dacca8f
Revises: 1008d077371a
Create Date: 2026-10-04 03:28:24.895003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d0e20dacca8f"
down_revision: Union[str, Sequence[str], None] = "1008d077371a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "underwriting_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "review_case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "requested_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "override_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "original_value",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "requested_value",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="REQUESTED",
        ),
        sa.Column(
            "approved_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "rejected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["underwriting_review_cases.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_admin_user_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_admin_user_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_underwriting_overrides_case_created",
        "underwriting_overrides",
        ["review_case_id", "created_at"],
    )

    op.create_index(
        "ix_underwriting_overrides_case_status",
        "underwriting_overrides",
        ["review_case_id", "status"],
    )

    op.create_index(
        "ix_underwriting_overrides_requested_by_created",
        "underwriting_overrides",
        ["requested_by_admin_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_underwriting_overrides_requested_by_created",
        table_name="underwriting_overrides",
    )
    op.drop_index(
        "ix_underwriting_overrides_case_status",
        table_name="underwriting_overrides",
    )
    op.drop_index(
        "ix_underwriting_overrides_case_created",
        table_name="underwriting_overrides",
    )
    op.drop_table("underwriting_overrides")