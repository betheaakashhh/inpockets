import asyncio
import hashlib
import uuid

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.services.document import DocumentService
from app.providers.storage import DocumentStorage, StoredDocument


class FakeConcurrentStorage(DocumentStorage):
    def __init__(self):
        self.documents = {}
        self.put_barrier = asyncio.Barrier(2)
        self.put_count = 0
        self.unique_refs = False

    async def put(
        self,
        content: bytes,
        content_type: str,
        key_hint: str,
    ) -> StoredDocument:
        import hashlib

        checksum = hashlib.sha256(content).hexdigest()

        self.put_count += 1

        storage_ref = (
            f"{key_hint}-{checksum}-{self.put_count}"
            if self.unique_refs
            else f"{key_hint}-{checksum}"
        )

        self.documents[storage_ref] = (content, content_type)

        # Force both requests to reach the DB after the storage operation.
        await self.put_barrier.wait()

        return StoredDocument(
            storage_ref=storage_ref,
            checksum=checksum,
            size_bytes=len(content),
        )

    async def get(self, storage_ref: str):
        content, content_type = self.documents[storage_ref]

        from app.providers.storage import StoredDocumentContent

        return StoredDocumentContent(
            content=content,
            content_type=content_type,
        )

    async def exists(self, storage_ref: str) -> bool:
        return storage_ref in self.documents

    async def delete(self, storage_ref: str) -> None:
        self.documents.pop(storage_ref, None)


@pytest.mark.asyncio
async def test_concurrent_duplicate_document_creation():
    owner_id = uuid.uuid4()
    content = b"same-concurrent-document"

    storage = FakeConcurrentStorage()

    async def create_document():
        async with AsyncSessionLocal() as session:
            service = DocumentService(session)
            service.storage = storage

            document = await service.store_document(
                owner_type="USER",
                owner_id=owner_id,
                document_type="IDENTITY_PROOF",
                content=content,
                content_type="application/pdf",
                key_hint="concurrent-document",
                immutable=True,
            )

            await session.commit()
            return document

    results = await asyncio.gather(
        create_document(),
        create_document(),
        return_exceptions=True,
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count(Document.id)).where(
                Document.owner_type == "USER",
                Document.owner_id == owner_id,
            )
        )
        document_count = result.scalar_one()
    exceptions = [result for result in results if isinstance(result, Exception)]
    
    assert not exceptions
    assert results[0].id == results[1].id
    assert document_count == 1

    

    # At this stage we intentionally allow the race to expose the
    # database IntegrityError. The next implementation step will
    # make both concurrent callers resolve safely.
    assert len(exceptions) <= 1
    

@pytest.mark.asyncio
async def test_concurrent_duplicate_document_cleans_losing_storage():
    owner_id = uuid.uuid4()
    content = b"same-concurrent-document-storage-race"

    storage = FakeConcurrentStorage()
    storage.unique_refs = True

    async def create_document():
        async with AsyncSessionLocal() as session:
            service = DocumentService(session)
            service.storage = storage

            document = await service.store_document(
                owner_type="USER",
                owner_id=owner_id,
                document_type="IDENTITY_PROOF",
                content=content,
                content_type="application/pdf",
                key_hint="concurrent-storage-race",
                immutable=True,
            )

            await session.commit()
            return document

    results = await asyncio.gather(
        create_document(),
        create_document(),
        return_exceptions=True,
    )

    exceptions = [
        result for result in results
        if isinstance(result, Exception)
    ]

    assert not exceptions
    assert results[0].id == results[1].id

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(
                Document.owner_type == "USER",
                Document.owner_id == owner_id,
            )
        )
        document = result.scalar_one()

    assert len(storage.documents) == 1
    assert document.storage_ref in storage.documents