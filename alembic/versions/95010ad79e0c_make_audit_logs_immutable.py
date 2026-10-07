"""make audit logs immutable

Revision ID: 95010ad79e0c
Revises: 9534e9d8830a
Create Date: 2026-10-07 02:37:16.635787

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "95010ad79e0c"
down_revision: Union[str, Sequence[str], None] = "9534e9d8830a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make audit log rows append-only."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only: UPDATE and DELETE are prohibited';
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE TRIGGER audit_logs_immutable_trigger
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    """Remove the audit log immutability trigger."""

    op.execute(
        """
        DROP TRIGGER IF EXISTS audit_logs_immutable_trigger
        ON audit_logs;
        """
    )

    op.execute(
        """
        DROP FUNCTION IF EXISTS prevent_audit_log_mutation();
        """
    )