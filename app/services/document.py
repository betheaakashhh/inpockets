from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.factory import get_document_storage
from app.providers.storage import DocumentStorage
from app.repositories.document import DocumentRepository


class DocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = DocumentRepository(session)
        self.storage: DocumentStorage = get_document_storage()
        self.settings = get_settings()

    def _validate_document(
        self,
        *,
        content: bytes,
        content_type: str,
    ) -> None:
        if not content:
            raise ValueError("Document content cannot be empty")

        if len(content) > self.settings.document_max_size_bytes:
            raise ValueError(
                "Document exceeds the maximum allowed size"
            )

        allowed_content_types = {
            item.strip().lower()
            for item in self.settings.document_allowed_content_types.split(",")
            if item.strip()
        }

        normalized_content_type = (
            content_type.split(";", 1)[0].strip().lower()
        )

        if normalized_content_type not in allowed_content_types:
            raise ValueError("Document content type is not allowed")

        self._validate_document_signature(
            content=content,
            content_type=content_type,
        )

    def _validate_document_signature(
        self,
        *,
        content: bytes,
        content_type: str,
    ) -> None:
        normalized_content_type = (
            content_type.split(";", 1)[0].strip().lower()
        )

        signatures = {
            "application/pdf": (b"%PDF-",),
            "image/jpeg": (b"\xff\xd8\xff",),
            "image/png": (b"\x89PNG\r\n\x1a\n",),
        }

        expected_signatures = signatures.get(normalized_content_type)

        if expected_signatures is None:
            raise ValueError("Document content type is not allowed")

        if not any(
            content.startswith(signature)
            for signature in expected_signatures
        ):
            raise ValueError(
                "Document content does not match its declared content type"
            )

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
        if not owner_type:
            raise ValueError("Document owner type is required")

        if not document_type:
            raise ValueError("Document type is required")

        if not content_type:
            raise ValueError("Document content type is required")

        self._validate_document(
            content=content,
            content_type=content_type,
        )

        checksum = self._checksum(content)

        existing = await self.repository.get_by_checksum(
            owner_type=owner_type,
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
            if existing_storage.storage_ref != stored.storage_ref:
                await self.storage.delete(stored.storage_ref)

            return existing_storage

        try:
            document = await self.repository.create(
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
        except IntegrityError:
            await self.session.rollback()

            existing = await self.repository.get_by_checksum(
                owner_type=owner_type,
                owner_id=owner_id,
                checksum=checksum,
            )

            if existing is not None:
                if existing.storage_ref != stored.storage_ref:
                    await self.storage.delete(stored.storage_ref)

                return existing

            existing_storage = await self.repository.get_by_storage_ref(
                stored.storage_ref
            )

            if existing_storage is not None:
                if (
                    existing_storage.owner_type == owner_type
                    and existing_storage.owner_id == owner_id
                    and existing_storage.checksum == checksum
                ):
                    return existing_storage

            raise

        return document

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

    async def get_document_for_owner(
        self,
        *,
        document_id: UUID,
        owner_type: str,
        owner_id: UUID,
    ):
        document = await self.repository.get_by_id_for_owner(
            document_id=document_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )

        if document is None:
            raise ValueError("Document not found")

        if not await self.storage.exists(document.storage_ref):
            raise ValueError("Document content is missing from storage")

        content = await self.storage.get(document.storage_ref)

        return document, content

    async def delete_document(self, document_id: UUID) -> None:
        document = await self.repository.get_by_id_for_update(
            document_id
        )

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

