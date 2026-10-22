"""e-sign manual review resolution columns

Revision ID: c3e9a7d4b815
Revises: b7d2e4f19a60
Create Date: 2026-10-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e9a7d4b815"
down_revision: Union[str, Sequence[str], None] = "b7d2e4f19a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "esign_transactions",
        sa.Column("reviewed_by_admin_user_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column("esign_transactions", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("esign_transactions", sa.Column("resolution_reason", sa.String(500)))
    op.create_foreign_key(
        "fk_esign_reviewed_by_admin_users",
        "esign_transactions",
        "admin_users",
        ["reviewed_by_admin_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_esign_review_pair",
        "esign_transactions",
        "(reviewed_by_admin_user_id IS NULL) = (reviewed_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_esign_review_pair", "esign_transactions", type_="check")
    op.drop_constraint("fk_esign_reviewed_by_admin_users", "esign_transactions", type_="foreignkey")
    op.drop_column("esign_transactions", "resolution_reason")
    op.drop_column("esign_transactions", "reviewed_at")
    op.drop_column("esign_transactions", "reviewed_by_admin_user_id")
