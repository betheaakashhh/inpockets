import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.onboarding import OnboardingStep
from app.domain.kyc import PANVerificationStatus
from app.models.pan_verification import PANVerification
from app.models.user_profile import UserProfile
from app.repositories.onboarding import OnboardingRepository
from app.repositories.onboarding_event import OnboardingEventRepository
from app.repositories.pan_verification import PANVerificationRepository
from app.repositories.user_profile import UserProfileRepository
from app.providers.factory import get_pan_provider

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class PANVerificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.pan_repository = PANVerificationRepository(session)
        self.profile_repository = UserProfileRepository(session)
        self.onboarding_repository = OnboardingRepository(session)
        self.event_repository = OnboardingEventRepository(session)
        self.provider = get_pan_provider()

    async def verify(
        self,
        *,
        user_id: UUID,
        pan_number: str,
    ) -> PANVerification:
        pan_number = pan_number.strip().upper()

        if not PAN_PATTERN.fullmatch(pan_number):
            raise ValueError("Invalid PAN format")

        onboarding = await self.onboarding_repository.get_by_user_id(user_id)
        if onboarding is None:
            raise ValueError("Onboarding has not started")

        if onboarding.current_step != OnboardingStep.PAN.value:
            raise ValueError(
                f"PAN verification is not allowed at onboarding step "
                f"{onboarding.current_step}"
            )

        latest = await self.pan_repository.get_latest_for_user(user_id=user_id)
        if latest is not None and latest.status == PANVerificationStatus.VERIFIED.value:
            return latest
        if latest is not None and latest.status == PANVerificationStatus.PENDING.value:
            return latest

        profile = await self.profile_repository.get_by_user_id(user_id)
        if profile is None or not profile.first_name or not profile.last_name:
            raise ValueError("First name and last name are required before PAN verification")

        full_name = f"{profile.first_name} {profile.last_name}".strip()
        result = await self.provider.verify(pan_number, full_name)

        record = await self.pan_repository.create(
            user_id=user_id,
            pan_number_masked=f"{pan_number[:2]}******{pan_number[-2:]}",
            provider=get_settings().pan_provider,
            provider_ref=result.provider_ref,
            status=result.status,
            verified_name=result.verified_name,
            name_match_result=result.name_match_result,
            failure_reason=result.failure_reason,
        )

        if result.status == PANVerificationStatus.VERIFIED.value:
            onboarding = await self.onboarding_repository.update(
                onboarding,
                current_step=OnboardingStep.KYC.value,
                status="IN_PROGRESS",
            )
            await self.event_repository.create(
                onboarding_id=onboarding.id,
                event_type="PAN_VERIFIED",
                event_metadata={"pan_verification_id": str(record.id)},
            )

        return record
