from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingRecord


class OnboardingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(
        self,
        user_id: UUID,
    ) -> OnboardingRecord | None:
        result = await self.session.execute(
            select(OnboardingRecord).where(
                OnboardingRecord.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        *,
        user_id: UUID,
    ) -> tuple[OnboardingRecord, bool]:
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing, False

        try:
            async with self.session.begin_nested():
                onboarding = OnboardingRecord(
                    user_id=user_id,
                    status="NOT_STARTED",
                    current_step="PROFILE",
                )
                self.session.add(onboarding)
                await self.session.flush()
        except IntegrityError:
            existing = await self.get_by_user_id(user_id)
            if existing is None:
                raise
            return existing, False

        return onboarding, True

    async def create(
        self,
        *,
        user_id: UUID,
    ) -> OnboardingRecord:
        onboarding, _ = await self.get_or_create(user_id=user_id)
        return onboarding

    async def update(
        self,
        onboarding: OnboardingRecord,
        *,
        status: str | None = None,
        current_step: str | None = None,
    ) -> OnboardingRecord:
        if status is not None:
            onboarding.status = status

        if current_step is not None:
            onboarding.current_step = current_step

        await self.session.flush()
        return onboarding
