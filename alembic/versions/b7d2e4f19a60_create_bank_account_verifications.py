"""create bank account verifications

Revision ID: b7d2e4f19a60
Revises: a91d3c7e5b02
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d2e4f19a60"
down_revision: Union[str, Sequence[str], None] = "a91d3c7e5b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_account_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("account_number_encrypted", sa.Text(), nullable=False),
        sa.Column("encryption_key_id", sa.String(50), nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),
        sa.Column("account_fingerprint", sa.String(64), nullable=False),
        sa.Column("ifsc", sa.String(11), nullable=False),
        sa.Column("bank_name", sa.String(100)),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_ref", sa.String(255)),
        sa.Column("client_reference", sa.String(128), nullable=False),
        sa.Column("name_match_result", sa.String(20)),
        sa.Column("failure_code", sa.String(50)),
        sa.Column("resolution_reason", sa.String(500)),
        sa.Column("reviewed_by_admin_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_admin_user_id"], ["admin_users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("provider", "provider_ref", name="uq_bank_verif_provider_ref"),
        sa.CheckConstraint(
            "status IN ('INITIATED','PENDING','VERIFIED','FAILED','MANUAL_REVIEW')",
            name="ck_bank_verif_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('PENDING','VERIFIED') OR provider_ref IS NOT NULL",
            name="ck_bank_verif_provider_ref_when_active",
        ),
        sa.CheckConstraint(
            "(status = 'VERIFIED') = (verified_at IS NOT NULL)",
            name="ck_bank_verif_verified_at_iff_verified",
        ),
        sa.CheckConstraint("account_last4 ~ '^[0-9]{4}$'", name="ck_bank_verif_last4"),
        sa.CheckConstraint("ifsc ~ '^[A-Z]{4}0[A-Z0-9]{6}$'", name="ck_bank_verif_ifsc"),
        sa.CheckConstraint("length(account_fingerprint) = 64", name="ck_bank_verif_fingerprint_len"),
        sa.CheckConstraint(
            "(reviewed_by_admin_user_id IS NULL) = (reviewed_at IS NULL)",
            name="ck_bank_verif_review_pair",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR status = 'VERIFIED'",
            name="ck_bank_verif_superseded_only_verified",
        ),
    )
    op.create_index("ix_bank_verif_user_requested", "bank_account_verifications", ["user_id", "requested_at"])
    op.create_index("ix_bank_verif_fingerprint", "bank_account_verifications", ["account_fingerprint"])
    op.create_index("ix_bank_verif_status_expires", "bank_account_verifications", ["status", "expires_at"])
    op.create_index(
        "uq_bank_verif_one_in_flight_per_user",
        "bank_account_verifications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('INITIATED','PENDING','MANUAL_REVIEW')"),
    )
    op.create_index(
        "uq_bank_verif_one_current_per_user",
        "bank_account_verifications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'VERIFIED' AND superseded_at IS NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION protect_bank_verification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Bank verification records cannot be deleted';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.provider IS DISTINCT FROM OLD.provider
                OR NEW.client_reference IS DISTINCT FROM OLD.client_reference
                OR NEW.account_last4 IS DISTINCT FROM OLD.account_last4
                OR NEW.account_fingerprint IS DISTINCT FROM OLD.account_fingerprint
                OR NEW.ifsc IS DISTINCT FROM OLD.ifsc
                OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
            THEN
                RAISE EXCEPTION 'Bank verification account binding is immutable';
            END IF;
            IF OLD.provider_ref IS NOT NULL
                AND NEW.provider_ref IS DISTINCT FROM OLD.provider_ref
            THEN
                RAISE EXCEPTION 'Bank verification provider reference is immutable once set';
            END IF;
            IF OLD.status IN ('VERIFIED', 'FAILED') THEN
                -- Terminal: only key rotation (ciphertext/key id) and superseding
                -- a verified account may change.
                IF NEW.status IS DISTINCT FROM OLD.status
                    OR NEW.bank_name IS DISTINCT FROM OLD.bank_name
                    OR NEW.name_match_result IS DISTINCT FROM OLD.name_match_result
                    OR NEW.failure_code IS DISTINCT FROM OLD.failure_code
                    OR NEW.resolution_reason IS DISTINCT FROM OLD.resolution_reason
                    OR NEW.reviewed_by_admin_user_id IS DISTINCT FROM OLD.reviewed_by_admin_user_id
                    OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
                    OR NEW.verified_at IS DISTINCT FROM OLD.verified_at
                    OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                THEN
                    RAISE EXCEPTION 'Finalised bank verification is immutable';
                END IF;
                IF OLD.superseded_at IS NOT NULL
                    AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at
                THEN
                    RAISE EXCEPTION 'Superseded bank verification is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_bank_verification_protect
        BEFORE UPDATE OR DELETE ON bank_account_verifications
        FOR EACH ROW EXECUTE FUNCTION protect_bank_verification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_bank_verification_protect ON bank_account_verifications;")
    op.execute("DROP FUNCTION IF EXISTS protect_bank_verification();")
    op.drop_table("bank_account_verifications")
