"""create e-sign transaction and event tables

Revision ID: a91d3c7e5b02
Revises: f4c2a9d81b36
Create Date: 2026-10-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a91d3c7e5b02"
down_revision: Union[str, Sequence[str], None] = "f4c2a9d81b36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "esign_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loan_offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loan_offer_version", sa.Integer(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_checksum", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_ref", sa.String(255)),
        sa.Column("client_reference", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.String(255)),
        sa.Column("signed_document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("signed_checksum", sa.String(64)),
        sa.Column("signed_at", sa.DateTime(timezone=True)),
        sa.Column("initiated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["loan_offer_id"], ["loan_offers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["signed_document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("provider", "provider_ref", name="uq_esign_provider_ref"),
        sa.CheckConstraint(
            "status IN ('INITIATED','PENDING','SIGNED','FAILED','EXPIRED','MANUAL_REVIEW')",
            name="ck_esign_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('PENDING','SIGNED') OR provider_ref IS NOT NULL",
            name="ck_esign_provider_ref_when_active",
        ),
        sa.CheckConstraint(
            "(status = 'SIGNED') = (signed_at IS NOT NULL)",
            name="ck_esign_signed_at_iff_signed",
        ),
        sa.CheckConstraint("loan_offer_version >= 1", name="ck_esign_offer_version"),
        sa.CheckConstraint("length(document_checksum) = 64", name="ck_esign_checksum_len"),
    )
    op.create_index("ix_esign_transactions_loan_offer_id", "esign_transactions", ["loan_offer_id"])
    op.create_index("ix_esign_user_status", "esign_transactions", ["user_id", "status"])
    op.create_index("ix_esign_status_expires", "esign_transactions", ["status", "expires_at"])
    op.create_index(
        "uq_esign_one_live_per_offer",
        "esign_transactions",
        ["loan_offer_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('INITIATED','PENDING','SIGNED','MANUAL_REVIEW')"),
    )

    op.create_table(
        "esign_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("esign_transaction_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reported_status", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("detail", sa.String(255)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["esign_transaction_id"], ["esign_transactions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_esign_event_provider_event"),
    )
    op.create_index("ix_esign_events_provider_ref", "esign_events", ["provider_ref"])
    op.create_index("ix_esign_events_esign_transaction_id", "esign_events", ["esign_transaction_id"])

    # A signed transaction is final evidence: its binding to the exact
    # document and its signed artifact can never be changed afterwards.
    op.execute(
        """
        CREATE FUNCTION prevent_signed_esign_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status = 'SIGNED' THEN
                RAISE EXCEPTION 'Signed e-sign transactions are immutable';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.loan_offer_id IS DISTINCT FROM OLD.loan_offer_id
                OR NEW.loan_offer_version IS DISTINCT FROM OLD.loan_offer_version
                OR NEW.document_id IS DISTINCT FROM OLD.document_id
                OR NEW.document_checksum IS DISTINCT FROM OLD.document_checksum
                OR NEW.provider IS DISTINCT FROM OLD.provider
                OR NEW.client_reference IS DISTINCT FROM OLD.client_reference
            THEN
                RAISE EXCEPTION 'E-sign document binding is immutable';
            END IF;
            IF OLD.provider_ref IS NOT NULL
                AND NEW.provider_ref IS DISTINCT FROM OLD.provider_ref
            THEN
                RAISE EXCEPTION 'E-sign provider reference is immutable once set';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_esign_transactions_immutable
        BEFORE UPDATE ON esign_transactions
        FOR EACH ROW EXECUTE FUNCTION prevent_signed_esign_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_esign_transactions_immutable ON esign_transactions;")
    op.execute("DROP FUNCTION IF EXISTS prevent_signed_esign_mutation();")
    op.drop_table("esign_events")
    op.drop_table("esign_transactions")
