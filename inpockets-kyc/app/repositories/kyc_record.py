import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kyc_record import KYCRecord


class KYCRecordRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        provider: str,
        provider_ref: str,
        kyc_type: str,
        consent_ref: str,
        initiated_at: datetime,
    ) -> KYCRecord:
        record = KYCRecord(
            user_id=user_id,
            provider=provider,
            provider_ref=provider_ref,
            kyc_type=kyc_type,
            consent_ref=consent_ref,
            status="initiated",
            initiated_at=initiated_at,
        )

        self.session.add(record)
        await self.session.flush()

        return record

    async def get_by_id(
        self,
        *,
        kyc_record_id: uuid.UUID,
    ) -> KYCRecord | None:
        result = await self.session.execute(
            select(KYCRecord).where(KYCRecord.id == kyc_record_id)
        )

        return result.scalar_one_or_none()

    async def get_latest_for_user(
        self,
        *,
        user_id: uuid.UUID,
    ) -> KYCRecord | None:
        result = await self.session.execute(
            select(KYCRecord)
            .where(KYCRecord.user_id == user_id)
            .order_by(KYCRecord.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def update(self, record: KYCRecord) -> KYCRecord:
        await self.session.flush()
        return record
