"""create late charge assessments

Revision ID: a8c4d1e6f203
Revises: f7a2c9d41b86
Create Date: 2026-10-25 02:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a8c4d1e6f203'
down_revision: Union[str, Sequence[str], None] = 'f7a2c9d41b86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FUNCTION = """
CREATE OR REPLACE FUNCTION protect_repayment_installment() RETURNS TRIGGER AS $$
DECLARE
    parent_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Repayment installments cannot be deleted';
    END IF;
    SELECT status INTO parent_status FROM repayment_schedules WHERE id = NEW.schedule_id;
    IF TG_OP = 'INSERT' THEN
        IF parent_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'Installments can only be added to a draft schedule';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.schedule_id IS DISTINCT FROM OLD.schedule_id
        OR NEW.installment_number IS DISTINCT FROM OLD.installment_number
        OR NEW.due_date IS DISTINCT FROM OLD.due_date
        OR NEW.principal_due IS DISTINCT FROM OLD.principal_due
        OR NEW.interest_due IS DISTINCT FROM OLD.interest_due
        OR NEW.fee_due %(fee_rule)s
    THEN
        RAISE EXCEPTION '%(message)s';
    END IF;
    IF parent_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Payments can only be applied to an active schedule';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table('late_charge_assessments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('installment_id', sa.UUID(), nullable=False),
    sa.Column('schedule_id', sa.UUID(), nullable=False),
    sa.Column('loan_offer_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('charge_date', sa.Date(), nullable=False),
    sa.Column('basis_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('BOUNCE','PENAL')", name='ck_late_charge_kind'),
    sa.CheckConstraint('amount > 0 AND basis_amount > 0', name='ck_late_charge_positive'),
    sa.ForeignKeyConstraint(['installment_id'], ['repayment_installments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['loan_offer_id'], ['loan_offers.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['schedule_id'], ['repayment_schedules.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('installment_id', 'charge_date', name='uq_late_charge_installment_day')
    )
    op.create_index('ix_late_charge_schedule', 'late_charge_assessments', ['schedule_id'], unique=False)
    op.execute(
        """
        CREATE FUNCTION late_charge_append_only() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Late charge assessments are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_late_charge_append_only
        BEFORE UPDATE OR DELETE ON late_charge_assessments
        FOR EACH ROW EXECUTE FUNCTION late_charge_append_only();
        """
    )
    # An installment's fee_due may now only GROW (a late charge is added); it
    # can never shrink, and every other due amount stays immutable.
    op.execute(
        _FUNCTION
        % {
            "fee_rule": "< OLD.fee_due",
            "message": "Installment due dates and amounts are immutable (fees may only increase)",
        }
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_late_charge_append_only ON late_charge_assessments;")
    op.execute("DROP FUNCTION IF EXISTS late_charge_append_only();")
    op.drop_index('ix_late_charge_schedule', table_name='late_charge_assessments')
    op.drop_table('late_charge_assessments')
    op.execute(
        _FUNCTION
        % {
            "fee_rule": "IS DISTINCT FROM OLD.fee_due",
            "message": "Installment due dates and amounts are immutable",
        }
    )
