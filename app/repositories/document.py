import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Document:
        record = Document(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_storage_ref(self, storage_ref: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.storage_ref == storage_ref)
        )
        return result.scalar_one_or_none()

    async def get_by_checksum(self, *, owner_id: uuid.UUID, checksum: str) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.owner_id == owner_id,
                Document.checksum == checksum,
            )
        )
        return result.scalar_one_or_none()
