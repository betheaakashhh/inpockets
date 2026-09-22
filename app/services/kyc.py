from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import OnboardingNotStartedError, UnsupportedProviderError, ValidationError
from app.domain.kyc import KYCStatus
from app.domain.onboarding import OnboardingStep
from app.repositories.consent import ConsentRepository
from app.repositories.kyc_record import KYCRecordRepository
from app.repositories.onboarding import OnboardingRepository
from app.repositories.onboarding_event import OnboardingEventRepository
from app.services.kyc import get_kyc_provider


KYC_CONSENT_TYPE = "KYC"


class KYCService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.provider = get_kyc_provider()
        self.consent_repository = ConsentRepository(session)
        self.kyc_repository = KYCRecordRepository(session)
        self.onboarding_repository = OnboardingRepository(session)
        self.event_repository = OnboardingEventRepository(session)

    async def initiate(self, *, user_id: UUID):
        onboarding = await self.onboarding_repository.get_by_user_id(user_id)
        if onboarding is None:
            raise OnboardingNotStartedError()

        if onboarding.current_step != OnboardingStep.KYC.value:
            raise ValidationError(
                f"KYC initiation is not allowed at onboarding step {onboarding.current_step}"
            )

        existing = await self.kyc_repository.get_latest_for_user(user_id=user_id)
        if existing and existing.status in {
            KYCStatus.PENDING.value,
            KYCStatus.PROCESSING.value,
            KYCStatus.VERIFIED.value,
        }:
            return existing, None

        consent = await self.consent_repository.get_by_user_and_type(
            user_id,
            KYC_CONSENT_TYPE,
        )
        if consent is None or consent.status.upper() != "GRANTED":
            raise ValidationError("Active KYC consent is required")

        result = await self.provider.initiate(str(user_id), str(consent.id))
        record = await self.kyc_repository.create(
            user_id=user_id,
            consent_id=consent.id,
            provider=get_settings().kyc_provider,
            provider_ref=result.provider_ref,
            kyc_type="DIGILOCKER",
            status=KYCStatus.PENDING.value,
        )
        await self.event_repository.create(
            onboarding_id=onboarding.id,
            event_type="KYC_INITIATED",
            event_metadata={"kyc_record_id": str(record.id)},
        )
        return record, result.consent_url

    async def refresh_status(self, *, user_id: UUID):
        record = await self.kyc_repository.get_latest_for_user(user_id=user_id)
        if record is None:
            return None

        result = await self.provider.get_status(record.provider_ref)
        try:
            status = KYCStatus(result.status)
        except ValueError as exc:
            raise UnsupportedProviderError(
                f"Unsupported KYC provider status: {result.status}"
            ) from exc

        record.status = status.value
        record.failure_reason = result.failure_reason

        if status == KYCStatus.VERIFIED:
            record.completed_at = datetime.now(timezone.utc)
            onboarding = await self.onboarding_repository.get_by_user_id(user_id)
            if onboarding and onboarding.current_step == OnboardingStep.KYC.value:
                onboarding.current_step = OnboardingStep.IDENTITY.value
                onboarding.status = "IN_PROGRESS"
                await self.event_repository.create(
                    onboarding_id=onboarding.id,
                    event_type="KYC_VERIFIED",
                    event_metadata={"kyc_record_id": str(record.id)},
                )

        return record
