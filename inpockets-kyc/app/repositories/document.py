import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        document_type: str,
        owner_type: str,
        owner_id: uuid.UUID,
        storage_ref: str,
        checksum: str,
        content_type: str,
        is_immutable: bool = False,
    ) -> Document:
        record = Document(
            document_type=document_type,
            owner_type=owner_type,
            owner_id=owner_id,
            storage_ref=storage_ref,
            checksum=checksum,
            content_type=content_type,
            is_immutable=is_immutable,
        )

        self.session.add(record)
        await self.session.flush()

        return record
