"""protect immutable documents at the database level

Revision ID: f4c2a9d81b36
Revises: e3b8f1c24a7d
Create Date: 2026-10-13

Issued KFS / agreement documents were only protected by service code. This
adds database enforcement:
  * a document attached to a loan offer must be flagged immutable;
  * an immutable document row can never be updated or deleted.
(TRUNCATE is not covered by row triggers; it is a superuser/maintenance action.)
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c2a9d81b36"
down_revision: Union[str, Sequence[str], None] = "e3b8f1c24a7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_documents_offer_documents_immutable",
        "documents",
        "loan_offer_id IS NULL OR is_immutable",
    )
    op.execute(
        """
        CREATE FUNCTION prevent_immutable_document_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.is_immutable THEN
                RAISE EXCEPTION
                    'Immutable documents cannot be updated or deleted';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_documents_immutable
        BEFORE UPDATE OR DELETE ON documents
        FOR EACH ROW
        EXECUTE FUNCTION prevent_immutable_document_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_documents_immutable ON documents;")
    op.execute("DROP FUNCTION IF EXISTS prevent_immutable_document_mutation();")
    op.drop_constraint(
        "ck_documents_offer_documents_immutable", "documents", type_="check"
    )
