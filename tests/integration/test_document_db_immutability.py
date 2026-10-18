"""The database itself must refuse to alter or remove immutable documents."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.document import Document


def make_doc(**kw):
    defaults = dict(
        document_type="KYC_DOCUMENT",
        owner_type="USER",
        owner_id=uuid4(),
        document_family_id=uuid4(),
        storage_ref=f"ref-{uuid4()}",
        checksum=uuid4().hex + uuid4().hex,
        content_type="application/pdf",
        size_bytes=10,
        version=1,
        is_immutable=False,
    )
    defaults.update(kw)
    return Document(**defaults)


async def test_immutable_document_cannot_be_updated_or_deleted(db_session):
    doc = make_doc(is_immutable=True)
    db_session.add(doc)
    await db_session.commit()
    doc_id = doc.id

    with pytest.raises(DBAPIError, match="Immutable documents"):
        await db_session.execute(
            update(Document).where(Document.id == doc_id).values(size_bytes=99)
        )
    await db_session.rollback()

    with pytest.raises(DBAPIError, match="Immutable documents"):
        await db_session.execute(delete(Document).where(Document.id == doc_id))
    await db_session.rollback()

    # cannot be "un-immutabled" either
    with pytest.raises(DBAPIError, match="Immutable documents"):
        await db_session.execute(
            update(Document).where(Document.id == doc_id).values(is_immutable=False)
        )
    await db_session.rollback()
    await db_session.execute(text("TRUNCATE documents CASCADE"))
    await db_session.commit()


async def test_mutable_document_can_still_be_changed_and_deleted(db_session):
    doc = make_doc(is_immutable=False)
    db_session.add(doc)
    await db_session.commit()

    await db_session.execute(
        update(Document).where(Document.id == doc.id).values(size_bytes=99)
    )
    await db_session.execute(delete(Document).where(Document.id == doc.id))
    await db_session.commit()


async def test_offer_documents_must_be_flagged_immutable(db_session, user, admin_user):
    from decimal import Decimal

    from app.models.loan_application import LoanApplication
    from app.models.loan_offer import LoanOffer

    application = LoanApplication(
        application_number=f"LA-{uuid4().hex[:20].upper()}",
        user_id=user.id,
        status="APPROVED",
        requested_amount=Decimal("1000"),
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()
    offer = LoanOffer(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("1000"),
        tenure_days=30,
        commercial_terms={},
        status="DRAFT",
    )
    db_session.add(offer)
    await db_session.flush()

    bad = make_doc(
        document_type="KFS",
        is_immutable=False,
        loan_offer_id=offer.id,
        loan_offer_version=1,
        template_key="kfs",
        template_version="v1",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError, match="ck_documents_offer_documents_immutable"):
        await db_session.flush()
    await db_session.rollback()
