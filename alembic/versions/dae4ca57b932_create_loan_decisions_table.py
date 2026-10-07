"""create loan decisions table

Revision ID: dae4ca57b932
Revises: 3b41c049ca39
Create Date: 2026-09-29 01:51:44.263032

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "dae4ca57b932"
down_revision: Union[str, Sequence[str], None] = "3b41c049ca39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "loan_decisions",
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
            "policy_evaluation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "policy_version",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "decision_route",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "recommended_amount",
            sa.Numeric(14, 2),
            nullable=True,
        ),
        sa.Column(
            "max_eligible_amount",
            sa.Numeric(14, 2),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
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
        sa.ForeignKeyConstraint(
            ["policy_evaluation_id"],
            ["policy_evaluations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_loan_decisions_loan_application_id",
        "loan_decisions",
        ["loan_application_id"],
    )
    op.create_index(
        "ix_loan_decisions_user_id",
        "loan_decisions",
        ["user_id"],
    )
    op.create_index(
        "ix_loan_decisions_policy_evaluation_id",
        "loan_decisions",
        ["policy_evaluation_id"],
    )
    op.create_index(
        "ix_loan_decisions_decision_route",
        "loan_decisions",
        ["decision_route"],
    )
    op.create_index(
        "ix_loan_decisions_decided_at",
        "loan_decisions",
        ["decided_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_loan_decisions_decided_at",
        table_name="loan_decisions",
    )
    op.drop_index(
        "ix_loan_decisions_decision_route",
        table_name="loan_decisions",
    )
    op.drop_index(
        "ix_loan_decisions_policy_evaluation_id",
        table_name="loan_decisions",
    )
    op.drop_index(
        "ix_loan_decisions_user_id",
        table_name="loan_decisions",
    )
    op.drop_index(
        "ix_loan_decisions_loan_application_id",
        table_name="loan_decisions",
    )
    op.drop_table("loan_decisions")