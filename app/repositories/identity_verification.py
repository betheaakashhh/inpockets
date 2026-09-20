import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity_verification import IdentityVerification


class IdentityVerificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> IdentityVerification:
        record = IdentityVerification(**kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, *, record_id: uuid.UUID) -> IdentityVerification | None:
        result = await self.session.execute(
            select(IdentityVerification).where(IdentityVerification.id == record_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_user(self, *, user_id: uuid.UUID) -> IdentityVerification | None:
        result = await self.session.execute(
            select(IdentityVerification)
            .where(IdentityVerification.user_id == user_id)
            .order_by(IdentityVerification.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update(self, record: IdentityVerification) -> IdentityVerification:
        await self.session.flush()
        return record
