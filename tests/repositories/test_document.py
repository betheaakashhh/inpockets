from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.repositories.document import DocumentRepository
from decimal import Decimal

from app.models.loan_application import LoanApplication
from app.repositories.loan_offer import LoanOfferRepository


@pytest.mark.asyncio
async def test_create_and_get_document(
    db_session: AsyncSession,
):
    owner_id = uuid4()

    repository = DocumentRepository(db_session)

    document = await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/test-document",
        checksum="a" * 64,
        content_type="application/pdf",
        size_bytes=1024,
        version=1,
        is_immutable=True,
    )

    assert document.id is not None
    assert document.owner_id == owner_id
    assert document.owner_type == "USER"
    assert document.document_type == "IDENTITY_PROOF"
    assert document.storage_ref == "documents/test-document"
    assert document.checksum == "a" * 64
    assert document.content_type == "application/pdf"
    assert document.size_bytes == 1024
    assert document.is_immutable is True

    fetched = await repository.get_by_id(document.id)

    assert fetched is not None
    assert fetched.id == document.id


@pytest.mark.asyncio
async def test_get_document_by_storage_ref(
    db_session: AsyncSession,
):
    repository = DocumentRepository(db_session)
    owner_id = uuid4()

    document = await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/test-document",
        checksum="a" * 64,
        content_type="application/pdf",
        size_bytes=1024,
        version=1,
        is_immutable=True,
    )

    fetched = await repository.get_by_storage_ref(
        "documents/test-document",
    )

    assert fetched is not None
    assert fetched.id == document.id


@pytest.mark.asyncio
async def test_get_document_by_checksum_and_owner(
    db_session: AsyncSession,
):
    repository = DocumentRepository(db_session)
    owner_id = uuid4()

    document = await repository.create(
        document_type="ADDRESS_PROOF",
        owner_type="USER",
        document_family_id=uuid4(),
        owner_id=owner_id,
        storage_ref="documents/address-proof",
        checksum="c" * 64,
        content_type="application/pdf",
        size_bytes=4096,
        version=1,
        is_immutable=False,
    )

    fetched = await repository.get_by_checksum(
        owner_type="USER",
        owner_id=owner_id,
        checksum="c" * 64,
    )

    assert fetched is not None
    assert fetched.id == document.id


@pytest.mark.asyncio
async def test_get_document_by_checksum_does_not_cross_owners(
    db_session: AsyncSession,
):
    repository = DocumentRepository(db_session)

    owner_id = uuid4()
    different_owner_id = uuid4()

    await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/owner-one",
        checksum="d" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=False,
    )

    fetched = await repository.get_by_checksum(
        owner_type="USER",
        owner_id=different_owner_id,
        checksum="d" * 64,
    )

    assert fetched is None


@pytest.mark.asyncio
async def test_list_documents_by_owner(
    db_session: AsyncSession,
):
    repository = DocumentRepository(db_session)
    owner_id = uuid4()

    first = await repository.create(
        document_type="PAN",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/pan",
        checksum="e" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=True,
    )

    second = await repository.create(
        document_type="ADDRESS_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/address",
        checksum="f" * 64,
        content_type="application/pdf",
        size_bytes=200,
        version=1,
        is_immutable=True,
    )

    documents = await repository.list_by_owner(
        owner_type="USER",
        owner_id=owner_id,
    )

    assert len(documents) == 2
    assert {document.id for document in documents} == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_list_documents_by_owner_and_type(
    db_session: AsyncSession,
):
    repository = DocumentRepository(db_session)
    owner_id = uuid4()

    matching = await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/identity-1",
        checksum="1" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=True,
    )

    await repository.create(
        document_type="ADDRESS_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/address-1",
        checksum="2" * 64,
        content_type="application/pdf",
        size_bytes=200,
        version=1,
        is_immutable=True,
    )

    documents = await repository.list_by_owner_and_type(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
    )

    assert len(documents) == 1
    assert documents[0].id == matching.id


@pytest.mark.asyncio
async def test_list_documents_by_owner_respects_owner_type(
    db_session: AsyncSession,
):
    repository = DocumentRepository(db_session)
    owner_id = uuid4()

    await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/user-identity",
        checksum="3" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=True,
    )

    await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="KYC_RECORD",
        owner_id=owner_id,
        document_family_id=uuid4(),
        storage_ref="documents/kyc-identity",
        checksum="4" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=True,
    )

    documents = await repository.list_by_owner(
        owner_type="USER",
        owner_id=owner_id,
    )

    assert len(documents) == 1
    assert documents[0].owner_type == "USER"

@pytest.mark.asyncio
async def test_get_by_id_for_update(db_session, user):
    repository = DocumentRepository(db_session)

    document = await repository.create(
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=user.id,
        document_family_id=uuid4(),
        storage_ref="documents/test-lock.pdf",
        checksum="a" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=True,
    )

    await db_session.commit()

    locked_document = await repository.get_by_id_for_update(document.id)

    assert locked_document is not None
    assert locked_document.id == document.id
    assert locked_document.is_immutable is True

@pytest.mark.asyncio
async def test_create_document_with_loan_offer_provenance(
    db_session: AsyncSession,
    user,
):
    application = LoanApplication(
        application_number="INP-DOC-PROVENANCE-001",
        user_id=user.id,
        status="MANUAL_REVIEW",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    offer_repository = LoanOfferRepository(db_session)
    offer = await offer_repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        version=1,
        principal_amount=Decimal("4500.00"),
        tenure_days=30,
        commercial_terms={
            "annual_interest_rate": "18.00",
            "processing_fee": "100.00",
            "currency": "INR",
        },
    )

    repository = DocumentRepository(db_session)
    document = await repository.create(
        document_type="KFS",
        owner_type="USER",
        owner_id=user.id,
        document_family_id=uuid4(),
        storage_ref="documents/loan-offer/kfs-v1",
        checksum="b" * 64,
        content_type="application/pdf",
        size_bytes=2048,
        version=1,
        is_immutable=True,
        loan_offer_id=offer.id,
        loan_offer_version=offer.version,
        template_key="loan_offer_kfs",
        template_version="1.0.0",
    )

    assert document.loan_offer_id == offer.id
    assert document.loan_offer_version == 1
    assert document.template_key == "loan_offer_kfs"
    assert document.template_version == "1.0.0"

    fetched = await repository.get_by_id(document.id)

    assert fetched is not None
    assert fetched.loan_offer_id == offer.id
    assert fetched.loan_offer_version == 1
    assert fetched.template_key == "loan_offer_kfs"
    assert fetched.template_version == "1.0.0"