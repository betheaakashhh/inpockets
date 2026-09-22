import uuid

import pytest

from app.models.document import Document
from app.providers.storage import StoredDocumentContent
from app.services.document import DocumentService


class FakeSettings:
    document_max_size_bytes = 10 * 1024 * 1024
    document_allowed_content_types = (
        "application/pdf,image/jpeg,image/png"
    )


class FakeStorage:
    def __init__(self):
        self.documents = {}

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ):
        import hashlib

        checksum = hashlib.sha256(content).hexdigest()
        storage_ref = f"{key_hint}-{checksum}"

        self.documents[storage_ref] = (
            content,
            content_type,
        )

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
        document = Document(
            id=uuid.uuid4(),
            **kwargs,
        )

        self.documents[document.id] = document

        return document

    async def get_by_id(self, document_id):
        return self.documents.get(document_id)
    
    async def get_by_id_for_owner(
        self,
        *,
        document_id,
        owner_type,
        owner_id,
    ):
        document = self.documents.get(document_id)

        if document is None:
            return None

        if (
            document.owner_type != owner_type
            or document.owner_id != owner_id
        ):
            return None

        return document

    async def get_by_storage_ref(self, storage_ref):
        for document in self.documents.values():
            if document.storage_ref == storage_ref:
                return document

        return None

    async def get_by_checksum(
        self,
        *,
        owner_type,
        owner_id,
        checksum,
    ):
        for document in self.documents.values():
            if (
                document.owner_type == owner_type
                and document.owner_id == owner_id
                and document.checksum == checksum
            ):
                return document

        return None

    async def delete(self, document):
        self.documents.pop(document.id, None)

    async def get_by_id_for_update(self, document_id):
        return self.documents.get(document_id)

    async def list_by_owner(
        self,
        *,
        owner_type,
        owner_id,
    ):
        return [
            document
            for document in self.documents.values()
            if (
                document.owner_type == owner_type
                and document.owner_id == owner_id
            )
        ]


@pytest.fixture
def service():
    service = object.__new__(DocumentService)
    service.repository = FakeRepository()
    service.storage = FakeStorage()
    service.settings = FakeSettings()

    return service


@pytest.mark.asyncio
async def test_store_document(service):
    owner_id = uuid.uuid4()
    content = b"%PDF-1.7\nvalid-test-content"

    document = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="test-document",
        immutable=True,
    )

    assert document.owner_type == "USER"
    assert document.owner_id == owner_id
    assert document.document_type == "IDENTITY_PROOF"
    assert document.content_type == "application/pdf"
    assert document.size_bytes == len(content)
    assert document.is_immutable is True


@pytest.mark.asyncio
async def test_store_document_returns_existing_duplicate(service):
    owner_id = uuid.uuid4()
    content = b"%PDF-1.7\nsame-document"

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
    with pytest.raises(
        ValueError,
        match="content cannot be empty",
    ):
        await service.store_document(
            owner_type="USER",
            owner_id=uuid.uuid4(),
            document_type="IDENTITY_PROOF",
            content=b"",
            content_type="application/pdf",
            key_hint="empty",
        )


@pytest.mark.asyncio
async def test_store_document_rejects_oversized_content(service):
    content = b"x" * (
        service.settings.document_max_size_bytes + 1
    )

    with pytest.raises(
        ValueError,
        match="exceeds the maximum allowed size",
    ):
        await service.store_document(
            owner_type="USER",
            owner_id=uuid.uuid4(),
            document_type="IDENTITY_PROOF",
            content=content,
            content_type="application/pdf",
            key_hint="oversized",
        )


@pytest.mark.asyncio
async def test_store_document_rejects_unsupported_content_type(service):
    with pytest.raises(
        ValueError,
        match="content type is not allowed",
    ):
        await service.store_document(
            owner_type="USER",
            owner_id=uuid.uuid4(),
            document_type="IDENTITY_PROOF",
            content=b"document-content",
            content_type="application/x-executable",
            key_hint="unsupported-type",
        )


@pytest.mark.asyncio
async def test_store_document_accepts_pdf(service):
    content = b"%PDF-1.7\nvalid-pdf-content"

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="valid-pdf",
    )

    assert document.content_type == "application/pdf"
    assert document.size_bytes == len(content)
    assert document.checksum == service._checksum(content)


@pytest.mark.asyncio
async def test_store_document_accepts_jpeg(service):
    content = b"\xff\xd8\xff\xe0" + b"jpeg-test-content"

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="PHOTO",
        content=content,
        content_type="image/jpeg",
        key_hint="valid-jpeg",
    )

    assert document.content_type == "image/jpeg"
    assert document.size_bytes == len(content)
    assert document.checksum == service._checksum(content)


@pytest.mark.asyncio
async def test_store_document_accepts_png(service):
    content = (
        b"\x89PNG\r\n\x1a\n"
        + b"png-test-content"
    )

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="PHOTO",
        content=content,
        content_type="image/png",
        key_hint="valid-png",
    )

    assert document.content_type == "image/png"
    assert document.size_bytes == len(content)
    assert document.checksum == service._checksum(content)


@pytest.mark.asyncio
async def test_store_document_rejects_mismatched_content_signature(
    service,
):
    with pytest.raises(
        ValueError,
        match="does not match its declared content type",
    ):
        await service.store_document(
            owner_type="USER",
            owner_id=uuid.uuid4(),
            document_type="IDENTITY_PROOF",
            content=b"this-is-not-a-pdf",
            content_type="application/pdf",
            key_hint="invalid-signature",
        )


@pytest.mark.asyncio
async def test_get_document_content(service):
    content = b"%PDF-1.7\nhello"

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="content-test",
    )

    stored_document, stored_content = (
        await service.get_document_content(document.id)
    )

    assert stored_document.id == document.id
    assert stored_content.content == content
    assert stored_content.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_get_document_fails_when_storage_object_missing(
    service,
):
    content = b"%PDF-1.7\nmissing-storage"

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="IDENTITY_PROOF",
        content=content,
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
    content = b"%PDF-1.7\nimmutable"

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="KYC_DOCUMENT",
        content=content,
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
    content = b"%PDF-1.7\ntemporary"

    document = await service.store_document(
        owner_type="USER",
        owner_id=uuid.uuid4(),
        document_type="TEMP_DOCUMENT",
        content=content,
        content_type="application/pdf",
        key_hint="mutable-test",
        immutable=False,
    )

    await service.delete_document(document.id)

    assert not await service.storage.exists(document.storage_ref)


@pytest.mark.asyncio
async def test_delete_document_uses_locked_lookup(service):
    document = Document(
        id=uuid.uuid4(),
        document_type="IDENTITY_PROOF",
        owner_type="USER",
        owner_id=uuid.uuid4(),
        storage_ref="documents/test.pdf",
        checksum="a" * 64,
        content_type="application/pdf",
        size_bytes=100,
        version=1,
        is_immutable=False,
    )

    service.repository.documents[document.id] = document

    deleted_storage_refs = []

    async def delete_storage(storage_ref):
        deleted_storage_refs.append(storage_ref)

    service.storage.delete = delete_storage

    await service.delete_document(document.id)

    assert deleted_storage_refs == [document.storage_ref]

@pytest.mark.asyncio
async def test_owner_can_retrieve_document(service):
    owner_id = uuid.uuid4()
    content = b"%PDF-1.7\nowner-document"

    document = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="owner-document",
    )

    retrieved_document, retrieved_content = (
        await service.get_document_for_owner(
            document_id=document.id,
            owner_type="USER",
            owner_id=owner_id,
        )
    )

    assert retrieved_document.id == document.id
    assert retrieved_document.owner_id == owner_id
    assert retrieved_content.content == content
    assert retrieved_content.content_type == "application/pdf"


@pytest.mark.asyncio
async def test_different_user_cannot_retrieve_document(service):
    owner_id = uuid.uuid4()
    different_user_id = uuid.uuid4()
    content = b"%PDF-1.7\nprivate-document"

    document = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="private-document",
    )

    with pytest.raises(
        ValueError,
        match="Document not found",
    ):
        await service.get_document_for_owner(
            document_id=document.id,
            owner_type="USER",
            owner_id=different_user_id,
        )


@pytest.mark.asyncio
async def test_nonexistent_document_returns_document_not_found(
    service,
):
    with pytest.raises(
        ValueError,
        match="Document not found",
    ):
        await service.get_document_for_owner(
            document_id=uuid.uuid4(),
            owner_type="USER",
            owner_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_owner_retrieval_fails_when_storage_object_missing(
    service,
):
    owner_id = uuid.uuid4()
    content = b"%PDF-1.7\nmissing-owner-storage"

    document = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=content,
        content_type="application/pdf",
        key_hint="missing-owner-storage",
    )

    await service.storage.delete(document.storage_ref)

    with pytest.raises(
        ValueError,
        match="missing from storage",
    ):
        await service.get_document_for_owner(
            document_id=document.id,
            owner_type="USER",
            owner_id=owner_id,
        )


@pytest.mark.asyncio
async def test_list_documents_only_returns_documents_for_owner(
    service,
):
    owner_id = uuid.uuid4()
    different_user_id = uuid.uuid4()

    owner_document = await service.store_document(
        owner_type="USER",
        owner_id=owner_id,
        document_type="IDENTITY_PROOF",
        content=b"%PDF-1.7\nowner-document-list",
        content_type="application/pdf",
        key_hint="owner-list",
    )

    other_document = await service.store_document(
        owner_type="USER",
        owner_id=different_user_id,
        document_type="IDENTITY_PROOF",
        content=b"%PDF-1.7\nother-document-list",
        content_type="application/pdf",
        key_hint="other-list",
    )

    documents = await service.list_documents(
        owner_type="USER",
        owner_id=owner_id,
    )

    assert len(documents) == 1
    assert documents[0].id == owner_document.id
    assert documents[0].owner_id == owner_id
    assert documents[0].id != other_document.id