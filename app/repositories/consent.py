from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import Consent


class ConsentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(
        self,
        user_id: UUID,
    ) -> list[Consent]:
        result = await self.session.execute(
            select(Consent)
            .where(Consent.user_id == user_id)
            .order_by(Consent.created_at.asc())
        )

        return list(result.scalars().all())

    async def get_by_user_and_type(
        self,
        user_id: UUID,
        consent_type: str,
    ) -> Consent | None:
        result = await self.session.execute(
            select(Consent)
            .where(
                Consent.user_id == user_id,
                Consent.consent_type == consent_type,
            )
            .order_by(Consent.created_at.desc())
        )

        return result.scalars().first()

    async def create(
        self,
        *,
        user_id: UUID,
        consent_type: str,
        version: str,
        status: str,
    ) -> Consent:
        consent = Consent(
            user_id=user_id,
            consent_type=consent_type,
            version=version,
            status=status,
        )

        self.session.add(consent)

        await self.session.flush()

        return consent