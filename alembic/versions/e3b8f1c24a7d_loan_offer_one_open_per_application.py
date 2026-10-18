"""enforce one open loan offer per application

Revision ID: e3b8f1c24a7d
Revises: a7114ea9db2e
Create Date: 2026-10-12

An application may have many offer versions, but only one may be live
(ISSUED or ACCEPTED) at a time. Without this, a superseded offer could still
be accepted by the customer after a newer version was issued.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b8f1c24a7d"
down_revision: Union[str, Sequence[str], None] = "a7114ea9db2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolve any pre-existing duplicates (dev data) before the index is built:
    # keep the newest open offer per application, cancel the older ones.
    op.execute(
        """
        UPDATE loan_offers o
        SET status = 'CANCELLED'
        WHERE o.status = 'ISSUED'
          AND EXISTS (
            SELECT 1 FROM loan_offers n
            WHERE n.loan_application_id = o.loan_application_id
              AND n.status IN ('ISSUED', 'ACCEPTED')
              AND n.version > o.version
          )
        """
    )
    op.create_index(
        "uq_loan_offers_one_open_per_application",
        "loan_offers",
        ["loan_application_id"],
        unique=True,
        postgresql_where="status IN ('ISSUED', 'ACCEPTED')",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_loan_offers_one_open_per_application",
        table_name="loan_offers",
    )
