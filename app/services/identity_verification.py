from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.kyc import IdentityVerificationStatus
from app.domain.onboarding import OnboardingStep
from app.providers.factory import get_identity_verification_provider
from app.repositories.identity_verification import IdentityVerificationRepository
from app.repositories.onboarding import OnboardingRepository
from app.repositories.onboarding_event import OnboardingEventRepository


class IdentityVerificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.provider = get_identity_verification_provider()
        self.repository = IdentityVerificationRepository(session)
        self.onboarding_repository = OnboardingRepository(session)
        self.event_repository = OnboardingEventRepository(session)

    async def start(self, *, user_id: UUID):
        onboarding = await self.onboarding_repository.get_by_user_id(user_id)
        if onboarding is None:
            raise ValueError("Onboarding has not started")
        if onboarding.current_step != OnboardingStep.IDENTITY.value:
            raise ValueError(
                f"Identity verification is not allowed at onboarding step {onboarding.current_step}"
            )

        existing = await self.repository.get_latest_for_user(user_id=user_id)
        if existing and existing.status in {
            IdentityVerificationStatus.PENDING.value,
            IdentityVerificationStatus.PROCESSING.value,
            IdentityVerificationStatus.VERIFIED.value,
        }:
            return existing, None

        session = await self.provider.start_session(str(user_id))
        record = await self.repository.create(
            user_id=user_id,
            provider="development",
            provider_ref=session.provider_ref,
            verification_type="LIVENESS",
            status=IdentityVerificationStatus.PENDING.value,
        )
        await self.event_repository.create(
            onboarding_id=onboarding.id,
            event_type="IDENTITY_VERIFICATION_STARTED",
            event_metadata={"identity_verification_id": str(record.id)},
        )
        return record, session.capture_session_token

    async def submit_capture(self, *, user_id: UUID, capture_ref: str):
        record = await self.repository.get_latest_for_user(user_id=user_id)
        if record is None:
            raise ValueError("Identity verification has not been started")

        if record.status not in {
            IdentityVerificationStatus.PENDING.value,
            IdentityVerificationStatus.RETRY_REQUIRED.value,
            IdentityVerificationStatus.PROCESSING.value,
        }:
            raise ValueError(
                f"Identity capture is not allowed while status is {record.status}"
            )

        result = await self.provider.submit_capture(record.provider_ref, capture_ref)
        return await self._apply_result(user_id=user_id, record=record, result=result)

    async def get_status(self, *, user_id: UUID):
        record = await self.repository.get_latest_for_user(user_id=user_id)
        if record is None:
            return None
        return record

    async def _apply_result(self, *, user_id, record, result):
        try:
            status = IdentityVerificationStatus(result.status)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported identity provider status: {result.status}"
            ) from exc

        record.status = status.value
        record.confidence_score = result.confidence_score
        record.failure_reason = result.failure_reason

        if status == IdentityVerificationStatus.VERIFIED:
            onboarding = await self.onboarding_repository.get_by_user_id(user_id)
            if onboarding and onboarding.current_step == OnboardingStep.IDENTITY.value:
                onboarding.current_step = OnboardingStep.COMPLETED.value
                onboarding.status = "COMPLETED"
                await self.event_repository.create(
                    onboarding_id=onboarding.id,
                    event_type="IDENTITY_VERIFIED",
                    event_metadata={"identity_verification_id": str(record.id)},
                )

        return record
