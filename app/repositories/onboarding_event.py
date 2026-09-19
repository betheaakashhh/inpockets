from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding_event import OnboardingEvent


class OnboardingEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        onboarding_id: UUID,
        event_type: str,
        event_metadata: dict | None = None,
    ) -> OnboardingEvent:
        event = OnboardingEvent(
            onboarding_id=onboarding_id,
            event_type=event_type,
            event_metadata=event_metadata,
        )

        self.session.add(event)

        await self.session.flush()

        return event

    async def get_by_onboarding_id(
        self,
        onboarding_id: UUID,
    ) -> list[OnboardingEvent]:
        result = await self.session.execute(
            select(OnboardingEvent)
            .where(OnboardingEvent.onboarding_id == onboarding_id)
            .order_by(OnboardingEvent.created_at.asc())
        )

        return list(result.scalars().all())