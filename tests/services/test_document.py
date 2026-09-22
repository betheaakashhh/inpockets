import uuid

import pytest

from app.providers.storage import StoredDocumentContent
from app.services.document import DocumentService


class FakeStorage:
    def __init__(self):
        self.documents = {}

    async def put(self, content: bytes, content_type: str, key_hint: str):
        import hashlib

        checksum = hashlib.sha256(content).hexdigest()
        storage_ref = f"{key_hint}-{checksum}"

        self.documents[storage_ref] = (content, content_type)

        from app.providers.storage import StoredDocument

        return StoredDocument(
            storage_ref=storage_ref,
            checksum=checksum,
            size_bytes=len(content),
        )

    async def get(self, storage_ref: str):
        if storage_ref not in self.documents:
            raise FileNotFoundError(storage_ref)

        content, content_type = self.documents[storage_ref]

        return StoredDocumentContent(
            content=content,
            content_type=content_type,
        )

    async def exists(self, storage_ref: str):
        return storage_ref in self.documents

    async def delete(self, storage_ref: str):
        self.documents.pop(storage_ref, None)


class FakeRepository:
    def __init__(self):
        self.documents = {}

    async def create(self, **kwargs):
        from app.models.document import Document

        document = Document(
            id=uuid.uuid4(),
            **kwargs,
        )
        self.documents[document.id] = document
        return document

    async def get_by_id(self, document_id):
        return self.documents.get(document_id)

    async def get_by_storage_ref(self, storage_ref):
        for document in self.documents.values():
            if document.storage_ref == storage_ref:
                return document
        return None

    async def get_by_checksum(self, *, owner_id, checksum):
        for document in self.documents.values():
            if (
                document.owner_id == owner_id
                and document.checksum == checksum
            ):
                return document
        return None
    async def delete(self, document):
       self.documents.pop(document.id, None)


@pytest.fixture
def service():
    service = object.__new__(DocumentService)
    service.repository = FakeRepository()
    service.storage = FakeStorage()
    return service


@pytest.mark.asyncio
async def test_store_document(service):
    owner_id = uuid.uuid4()

    document = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=b"document-content",
        content_type="application/pdf",
        key_hint="test-document",
        immutable=True,
    )

    assert document.owner_type == "USER"
    assert document.owner_id == owner_id
    assert document.document_type == "IDENTITY_PROOF"
    assert document.content_type == "application/pdf"
    assert document.size_bytes == len(b"document-content")
    assert document.is_immutable is True


@pytest.mark.asyncio
async def test_store_document_returns_existing_duplicate(service):
    owner_id = uuid.uuid4()
    content = b"same-document"

    first = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="first",
    )

    second = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="second",
    )

    assert second.id == first.id


@pytest.mark.asyncio
async def test_store_document_rejects_empty_content(service):
    with pytest.raises(ValueError, match="content cannot be empty"):
        await service.store_document(
            owner_type="USER",
            owner_id=uuid.uuid4(),
            document_type="IDENTITY_PROOF",
            content=b"",
            content_type="application/pdf",
            key_hint="empty",
        )


@pytest.mark.asyncio
async def test_get_document_content(service):
    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="IDENTITY_PROOF",
        content=b"hello",
        content_type="application/pdf",
        key_hint="content-test",
    )

    stored_document, content = await service.get_document_content(document.id)

    assert stored_document.id == document.id
    assert content.content == b"hello"
    assert content.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_get_document_fails_when_storage_object_missing(service):
    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="IDENTITY_PROOF",
        content=b"hello",
        content_type="application/pdf",
        key_hint="missing-test",
    )

    await service.storage.delete(document.storage_ref)

    with pytest.raises(
        ValueError,
        match="missing from storage",
    ):
        await service.get_document(document.id)


@pytest.mark.asyncio
async def test_immutable_document_cannot_be_deleted(service):
    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="KYC_DOCUMENT",
        content=b"immutable",
        content_type="application/pdf",
        key_hint="immutable-test",
        immutable=True,
    )

    with pytest.raises(
        ValueError,
        match="Immutable documents cannot be deleted",
    ):
        await service.delete_document(document.id)


@pytest.mark.asyncio
async def test_mutable_document_can_be_deleted(service):
    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="TEMP_DOCUMENT",
        content=b"temporary",
        content_type="application/pdf",
        key_hint="mutable-test",
        immutable=False,
    )

    await service.delete_document(document.id)

    assert not await service.storage.exists(document.storage_ref)