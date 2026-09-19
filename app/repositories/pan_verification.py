import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pan_verification import PANVerification


class PANVerificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> PANVerification:
        record = PANVerification(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, record_id: uuid.UUID) -> PANVerification | None:
        result = await self.session.execute(
            select(PANVerification).where(PANVerification.id == record_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_user(self, *, user_id: uuid.UUID) -> PANVerification | None:
        result = await self.session.execute(
            select(PANVerification)
            .where(PANVerification.user_id == user_id)
            .order_by(PANVerification.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
