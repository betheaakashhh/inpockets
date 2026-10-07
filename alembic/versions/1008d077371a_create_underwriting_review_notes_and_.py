"""create underwriting review notes and evidence tables

Revision ID: 1008d077371a
Revises: 4c7e91a2d5f0
Create Date: 2026-10-02 03:14:17.107089

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1008d077371a"
down_revision: Union[str, None] = "4c7e91a2d5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "underwriting_review_notes",
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
            "author_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["underwriting_review_cases.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_admin_user_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_underwriting_review_notes_review_case_id",
        "underwriting_review_notes",
        ["review_case_id"],
    )
    op.create_index(
        "ix_underwriting_review_notes_author_admin_user_id",
        "underwriting_review_notes",
        ["author_admin_user_id"],
    )
    op.create_index(
        "ix_underwriting_review_notes_case_created",
        "underwriting_review_notes",
        ["review_case_id", "created_at"],
    )
    op.create_index(
        "ix_underwriting_review_notes_author_created",
        "underwriting_review_notes",
        ["author_admin_user_id", "created_at"],
    )

    op.create_table(
        "underwriting_review_evidence",
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
            "added_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "evidence_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "reference",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["underwriting_review_cases.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_admin_user_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_underwriting_review_evidence_review_case_id",
        "underwriting_review_evidence",
        ["review_case_id"],
    )
    op.create_index(
        "ix_underwriting_review_evidence_added_by_admin_user_id",
        "underwriting_review_evidence",
        ["added_by_admin_user_id"],
    )
    op.create_index(
        "ix_underwriting_review_evidence_case_created",
        "underwriting_review_evidence",
        ["review_case_id", "created_at"],
    )
    op.create_index(
        "ix_underwriting_review_evidence_type",
        "underwriting_review_evidence",
        ["evidence_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_underwriting_review_evidence_type",
        table_name="underwriting_review_evidence",
    )
    op.drop_index(
        "ix_underwriting_review_evidence_case_created",
        table_name="underwriting_review_evidence",
    )
    op.drop_index(
        "ix_underwriting_review_evidence_added_by_admin_user_id",
        table_name="underwriting_review_evidence",
    )
    op.drop_index(
        "ix_underwriting_review_evidence_review_case_id",
        table_name="underwriting_review_evidence",
    )
    op.drop_table("underwriting_review_evidence")

    op.drop_index(
        "ix_underwriting_review_notes_author_created",
        table_name="underwriting_review_notes",
    )
    op.drop_index(
        "ix_underwriting_review_notes_case_created",
        table_name="underwriting_review_notes",
    )
    op.drop_index(
        "ix_underwriting_review_notes_author_admin_user_id",
        table_name="underwriting_review_notes",
    )
    op.drop_index(
        "ix_underwriting_review_notes_review_case_id",
        table_name="underwriting_review_notes",
    )
    op.drop_table("underwriting_review_notes")