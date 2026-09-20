import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kyc_document import KYCDocument


class KYCDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> KYCDocument:
        record = KYCDocument(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_provider_ref(self, *, kyc_record_id: uuid.UUID, provider_document_ref: str) -> KYCDocument | None:
        result = await self.session.execute(
            select(KYCDocument).where(
                KYCDocument.kyc_record_id == kyc_record_id,
                KYCDocument.provider_document_ref == provider_document_ref,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_ref_for_update(
        self, *, kyc_record_id: uuid.UUID, provider_document_ref: str
    ) -> KYCDocument | None:
        result = await self.session.execute(
            select(KYCDocument)
            .where(
                KYCDocument.kyc_record_id == kyc_record_id,
                KYCDocument.provider_document_ref == provider_document_ref,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_for_kyc_record(self, *, kyc_record_id: uuid.UUID) -> list[KYCDocument]:
        result = await self.session.execute(
            select(KYCDocument)
            .where(KYCDocument.kyc_record_id == kyc_record_id)
            .order_by(KYCDocument.retrieved_at.asc())
        )
        return list(result.scalars().all())

    async def count_for_kyc_record(self, *, kyc_record_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(KYCDocument.id).where(KYCDocument.kyc_record_id == kyc_record_id)
        )
        return len(result.scalars().all())
