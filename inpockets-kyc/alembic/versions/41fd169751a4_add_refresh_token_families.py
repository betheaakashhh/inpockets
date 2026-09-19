"""add refresh token families

Revision ID: 41fd169751a4

Revises: c77464bb70e0

Create Date: 2026-09-16 18:01:36.510571
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "41fd169751a4"
down_revision: str | Sequence[str] | None = "c77464bb70e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    # Existing sessions need a token family ID before the column
    # can safely become NOT NULL.
    op.add_column(
        "user_sessions",
        sa.Column(
            "token_family_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE user_sessions
            SET token_family_id = gen_random_uuid()
            WHERE token_family_id IS NULL
            """
        )
    )

    op.alter_column(
        "user_sessions",
        "token_family_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )

    op.add_column(
        "user_sessions",
        sa.Column(
            "revocation_reason",
            sa.String(length=30),
            nullable=True,
        ),
    )

    op.create_index(
        op.f("ix_user_sessions_token_family_id"),
        "user_sessions",
        ["token_family_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        op.f("ix_user_sessions_token_family_id"),
        table_name="user_sessions",
    )

    op.drop_column(
        "user_sessions",
        "revocation_reason",
    )

    op.drop_column(
        "user_sessions",
        "token_family_id",
    )