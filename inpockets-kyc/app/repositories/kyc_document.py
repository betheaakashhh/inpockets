import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kyc_document import KYCDocument


class KYCDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        kyc_record_id: uuid.UUID,
        document_id: uuid.UUID,
        document_type: str,
        retrieved_at: datetime,
    ) -> KYCDocument:
        record = KYCDocument(
            kyc_record_id=kyc_record_id,
            document_id=document_id,
            document_type=document_type,
            retrieved_at=retrieved_at,
        )

        self.session.add(record)
        await self.session.flush()

        return record

    async def count_for_kyc_record(
        self,
        *,
        kyc_record_id: uuid.UUID,
    ) -> int:
        result = await self.session.execute(
            select(KYCDocument).where(KYCDocument.kyc_record_id == kyc_record_id)
        )

        return len(result.scalars().all())
