"""create disbursements and disbursement events

Revision ID: d5a1c8e27f94
Revises: c3e9a7d4b815
Create Date: 2026-10-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5a1c8e27f94"
down_revision: Union[str, Sequence[str], None] = "c3e9a7d4b815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _fk(col, table, name, ondelete="RESTRICT"):
    return sa.ForeignKeyConstraint([col], [f"{table}.id"], name=name, ondelete=ondelete)


def upgrade() -> None:
    op.create_table(
        "disbursements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("loan_application_id", UUID, nullable=False),
        sa.Column("loan_offer_id", UUID, nullable=False),
        sa.Column("loan_offer_version", sa.Integer(), nullable=False),
        sa.Column("esign_transaction_id", UUID, nullable=False),
        sa.Column("bank_verification_id", UUID, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("beneficiary_last4", sa.String(4), nullable=False),
        sa.Column("beneficiary_ifsc", sa.String(11), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("retry_of_id", UUID),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_ref", sa.String(255)),
        sa.Column("utr", sa.String(64)),
        sa.Column("failure_code", sa.String(50)),
        sa.Column("review_reason", sa.String(100)),
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False),
        sa.Column("requested_by_admin_user_id", UUID),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk("user_id", "users", "fk_disbursements_user_id_users"),
        _fk("loan_application_id", "loan_applications", "fk_disbursements_application"),
        _fk("loan_offer_id", "loan_offers", "fk_disbursements_offer"),
        _fk("esign_transaction_id", "esign_transactions", "fk_disbursements_esign"),
        _fk("bank_verification_id", "bank_account_verifications", "fk_disbursements_bank_verification"),
        _fk("retry_of_id", "disbursements", "fk_disbursements_retry_of"),
        _fk("requested_by_admin_user_id", "admin_users", "fk_disbursements_requested_by"),
        sa.UniqueConstraint("idempotency_key", name="uq_disbursement_idempotency_key"),
        sa.UniqueConstraint("provider", "provider_ref", name="uq_disbursement_provider_ref"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCESS','FAILED','REVERSED','REQUIRES_REVIEW')",
            name="ck_disbursement_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_disbursement_amount_positive"),
        sa.CheckConstraint(
            "status NOT IN ('SUCCESS','REVERSED') OR provider_ref IS NOT NULL",
            name="ck_disbursement_provider_ref_when_paid",
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCESS','REVERSED')) = (completed_at IS NOT NULL)",
            name="ck_disbursement_completed_iff_paid",
        ),
        sa.CheckConstraint(
            "(status = 'REVERSED') = (reversed_at IS NOT NULL)",
            name="ck_disbursement_reversed_at_iff_reversed",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_disbursement_attempt"),
        sa.CheckConstraint("beneficiary_last4 ~ '^[0-9]{4}$'", name="ck_disbursement_last4"),
    )
    op.create_index("ix_disbursement_status_requested", "disbursements", ["status", "requested_at"])
    op.create_index("ix_disbursement_offer", "disbursements", ["loan_offer_id"])
    op.create_index("ix_disbursement_user", "disbursements", ["user_id"])
    op.create_index(
        "uq_disbursement_one_live_per_offer",
        "disbursements",
        ["loan_offer_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','PROCESSING','SUCCESS','REQUIRES_REVIEW')"),
    )

    op.create_table(
        "disbursement_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("disbursement_id", UUID),
        sa.Column("reported_status", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk("disbursement_id", "disbursements", "fk_disbursement_events_disbursement"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_disbursement_event_provider_event"),
    )
    op.create_index("ix_disbursement_events_provider_ref", "disbursement_events", ["provider_ref"])
    op.create_index("ix_disbursement_events_disbursement_id", "disbursement_events", ["disbursement_id"])

    op.execute(
        """
        CREATE FUNCTION protect_disbursement()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Disbursement records cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.loan_application_id IS DISTINCT FROM OLD.loan_application_id
                OR NEW.loan_offer_id IS DISTINCT FROM OLD.loan_offer_id
                OR NEW.loan_offer_version IS DISTINCT FROM OLD.loan_offer_version
                OR NEW.esign_transaction_id IS DISTINCT FROM OLD.esign_transaction_id
                OR NEW.bank_verification_id IS DISTINCT FROM OLD.bank_verification_id
                OR NEW.amount IS DISTINCT FROM OLD.amount
                OR NEW.currency IS DISTINCT FROM OLD.currency
                OR NEW.beneficiary_last4 IS DISTINCT FROM OLD.beneficiary_last4
                OR NEW.beneficiary_ifsc IS DISTINCT FROM OLD.beneficiary_ifsc
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.attempt IS DISTINCT FROM OLD.attempt
                OR NEW.provider IS DISTINCT FROM OLD.provider
                OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
                OR NEW.retry_of_id IS DISTINCT FROM OLD.retry_of_id
            THEN
                RAISE EXCEPTION 'Disbursement binding (amount, beneficiary, offer, key) is immutable';
            END IF;
            IF OLD.provider_ref IS NOT NULL
                AND NEW.provider_ref IS DISTINCT FROM OLD.provider_ref
            THEN
                RAISE EXCEPTION 'Disbursement provider reference is immutable once set';
            END IF;
            IF OLD.status = 'REVERSED' THEN
                RAISE EXCEPTION 'Reversed disbursement is immutable';
            END IF;
            IF OLD.status = 'SUCCESS' THEN
                IF NEW.status NOT IN ('SUCCESS', 'REVERSED')
                    OR NEW.utr IS DISTINCT FROM OLD.utr
                    OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                THEN
                    RAISE EXCEPTION 'A successful disbursement can only be reversed';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_disbursement_protect
        BEFORE UPDATE OR DELETE ON disbursements
        FOR EACH ROW EXECUTE FUNCTION protect_disbursement();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_disbursement_protect ON disbursements;")
    op.execute("DROP FUNCTION IF EXISTS protect_disbursement();")
    op.drop_table("disbursement_events")
    op.drop_table("disbursements")
