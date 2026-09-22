import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(
        self,
        document_id: uuid.UUID,
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_owner(
        self,
        *,
        document_id: uuid.UUID,
        owner_type: str,
        owner_id: uuid.UUID,
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.owner_type == owner_type,
                Document.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> Document:
        record = Document(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_storage_ref(
        self,
        storage_ref: str,
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.storage_ref == storage_ref)
        )
        return result.scalar_one_or_none()

    async def get_by_checksum(
        self,
        *,
        owner_type: str,
        owner_id: uuid.UUID,
        checksum: str,
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.owner_type == owner_type,
                Document.owner_id == owner_id,
                Document.checksum == checksum,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_owner(
        self,
        *,
        owner_type: str,
        owner_id: uuid.UUID,
    ) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(
                Document.owner_type == owner_type,
                Document.owner_id == owner_id,
            )
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_owner_and_type(
        self,
        *,
        owner_type: str,
        owner_id: uuid.UUID,
        document_type: str,
    ) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(
                Document.owner_type == owner_type,
                Document.owner_id == owner_id,
                Document.document_type == document_type,
            )
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete(self, document: Document) -> None:
        await self.session.delete(document)
        await self.session.flush()

    async def get_by_id_for_update(
        self,
        document_id: uuid.UUID,
    ) -> Document | None:
        result = await self.session.execute(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

