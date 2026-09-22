from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.repositories.document import DocumentRepository


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

    document = await repository.create(
        document_type="KYC_DOCUMENT",
        owner_type="KYC_RECORD",
        owner_id=uuid4(),
        storage_ref="kyc/document-123",
        checksum="b" * 64,
        content_type="image/jpeg",
        size_bytes=2048,
        version=1,
        is_immutable=True,
    )

    fetched = await repository.get_by_storage_ref(
        "kyc/document-123",
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