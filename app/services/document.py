from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.factory import get_document_storage
from app.providers.storage import DocumentStorage
from app.repositories.document import DocumentRepository


class DocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = DocumentRepository(session)
        self.storage: DocumentStorage = get_document_storage()

    async def store_document(
        self,
        *,
        owner_type: str,
        owner_id: UUID,
        document_type: str,
        content: bytes,
        content_type: str,
        key_hint: str,
        immutable: bool = False,
    ):
        if not content:
            raise ValueError("Document content cannot be empty")

        if not owner_type:
            raise ValueError("Document owner type is required")

        if not document_type:
            raise ValueError("Document type is required")

        if not content_type:
            raise ValueError("Document content type is required")

        checksum = self._checksum(content)

        existing = await self.repository.get_by_checksum(
            owner_id=owner_id,
            checksum=checksum,
        )

        if existing is not None:
            return existing

        storage_key = (
         f"{owner_type.lower()}/"
         f"{owner_id}/"
         f"{checksum}"
        )

        stored = await self.storage.put(
        content=content,
        content_type=content_type,
        key_hint=storage_key,
        )

        existing_storage = await self.repository.get_by_storage_ref(
            stored.storage_ref
        )

        if existing_storage is not None:
            return existing_storage

        return await self.repository.create(
            document_type=document_type,
            owner_type=owner_type,
            owner_id=owner_id,
            storage_ref=stored.storage_ref,
            checksum=stored.checksum,
            content_type=content_type,
            size_bytes=stored.size_bytes,
            version=1,
            is_immutable=immutable,
        )

    async def get_document(self, document_id: UUID):
        document = await self.repository.get_by_id(document_id)

        if document is None:
            raise ValueError("Document not found")

        if not await self.storage.exists(document.storage_ref):
            raise ValueError("Document content is missing from storage")

        return document

    async def get_document_content(self, document_id: UUID):
        document = await self.repository.get_by_id(document_id)

        if document is None:
            raise ValueError("Document not found")

        content = await self.storage.get(document.storage_ref)

        return document, content

    
    async def delete_document(self, document_id: UUID) -> None:
        document = await self.repository.get_by_id(document_id)

        if document is None:
            raise ValueError("Document not found")

        if document.is_immutable:
            raise ValueError("Immutable documents cannot be deleted")

        await self.storage.delete(document.storage_ref)
        await self.repository.delete(document)


        
    async def list_documents(
        self,
        *,
        owner_type: str,
        owner_id: UUID,
    ):
        return await self.repository.list_by_owner(
            owner_type=owner_type,
            owner_id=owner_id,
        )
    @staticmethod
    def _checksum(content: bytes) -> str:
        import hashlib

        return hashlib.sha256(content).hexdigest()
    
    