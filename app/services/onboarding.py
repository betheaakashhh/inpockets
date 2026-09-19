from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingRecord
from app.models.user_profile import UserProfile
from app.repositories.consent import ConsentRepository
from app.repositories.onboarding import OnboardingRepository
from app.repositories.onboarding_event import OnboardingEventRepository
from app.repositories.user_profile import UserProfileRepository
from app.domain.onboarding import (
    OnboardingStatus,
    OnboardingStep,
    is_valid_step_transition,
)

class OnboardingService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.profile_repository = UserProfileRepository(session)
        self.onboarding_repository = OnboardingRepository(session)
        self.event_repository = OnboardingEventRepository(session)
        self.consent_repository = ConsentRepository(session)

    async def get_or_create_onboarding(
        self,
        *,
        user_id: UUID,
    ) -> OnboardingRecord:
        onboarding = await self.onboarding_repository.get_by_user_id(user_id)

        if onboarding is not None:
            return onboarding

        onboarding = await self.onboarding_repository.create(
            user_id=user_id,
        )

        await self.event_repository.create(
            onboarding_id=onboarding.id,
            event_type="ONBOARDING_STARTED",
        )

        return onboarding

    async def get_or_create_profile(
        self,
        *,
        user_id: UUID,
    ) -> UserProfile:
        profile = await self.profile_repository.get_by_user_id(user_id)

        if profile is not None:
            return profile

        return await self.profile_repository.create(
            user_id=user_id,
        )

    async def update_profile(
        self,
        *,
        user_id: UUID,
        first_name: str | None = None,
        last_name: str | None = None,
        date_of_birth: date | None = None,
        gender: str | None = None,
    ) -> UserProfile:
        profile = await self.get_or_create_profile(user_id=user_id)

        return await self.profile_repository.update(
            profile,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date_of_birth,
            gender=gender,
        )

    async def update_onboarding_step(
    self,
    *,
    user_id: UUID,
    current_step: str,
) -> OnboardingRecord:
        onboarding = await self.get_or_create_onboarding(user_id=user_id)

        try:
            previous_step = OnboardingStep(onboarding.current_step)
            next_step = OnboardingStep(current_step)
        except ValueError as exc:
            raise ValueError("Invalid onboarding step") from exc

        if not is_valid_step_transition(previous_step, next_step):
            raise ValueError(
                f"Invalid onboarding step transition: "
                f"{previous_step.value} -> {next_step.value}"
            )

        if previous_step == next_step:
            return onboarding

        status = (
            OnboardingStatus.COMPLETED
            if next_step == OnboardingStep.COMPLETED
            else OnboardingStatus.IN_PROGRESS
        )

        onboarding = await self.onboarding_repository.update(
            onboarding,
            status=status.value,
            current_step=next_step.value,
        )

        await self.event_repository.create(
            onboarding_id=onboarding.id,
            event_type="ONBOARDING_STEP_CHANGED",
            event_metadata={
                "from": previous_step.value,
                "to": next_step.value,
            },
        )

        return onboarding

    async def record_consent(
        self,
        *,
        user_id: UUID,
        consent_type: str,
        version: str,
        status: str,
    ):
        return await self.consent_repository.create(
            user_id=user_id,
            consent_type=consent_type,
            version=version,
            status=status,
        )