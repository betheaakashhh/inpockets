from uuid import uuid4

import pytest

import app.services.identity_verification as identity_service
from app.models.consent import Consent
from app.models.kyc_record import KYCRecord
from app.models.onboarding import OnboardingRecord
from app.providers.identity_verification import IdentityVerificationResult
from app.core.exceptions import ValidationError
from app.services.identity_verification import IdentityVerificationService


class FakeIdentityProvider:
    async def start_session(self, user_id: str):
        from app.providers.identity_verification import IdentityVerificationSession

        return IdentityVerificationSession(
            provider_ref=f"identity-{user_id}",
            capture_session_token="capture-token",
        )

    async def submit_capture(self, provider_ref: str, capture_ref: str):
        return IdentityVerificationResult(
            status="VERIFIED",
            confidence_score=0.98,
        )


@pytest.mark.asyncio
async def test_start_identity_verification(db_session, user, monkeypatch):
    monkeypatch.setattr(
        identity_service,
        "get_identity_verification_provider",
        lambda: FakeIdentityProvider(),
    )

    onboarding = OnboardingRecord(
        user_id=user.id,
        status="IN_PROGRESS",
        current_step="IDENTITY",
    )
    consent = Consent(
        user_id=user.id,
        consent_type="KYC",
        version="1.0",
        status="GRANTED",
    )
    db_session.add_all([onboarding, consent])
    await db_session.flush()

    service = IdentityVerificationService(db_session)
    record, token = await service.start(user_id=user.id)

    assert record.status == "PENDING"
    assert record.verification_type == "LIVENESS"
    assert token == "capture-token"


@pytest.mark.asyncio
async def test_submit_verified_identity_completes_onboarding(
    db_session,
    user,
    monkeypatch,
):
    monkeypatch.setattr(
        identity_service,
        "get_identity_verification_provider",
        lambda: FakeIdentityProvider(),
    )

    onboarding = OnboardingRecord(
        user_id=user.id,
        status="IN_PROGRESS",
        current_step="IDENTITY",
    )
    db_session.add(onboarding)
    await db_session.flush()

    service = IdentityVerificationService(db_session)
    record, _ = await service.start(user_id=user.id)
    result = await service.submit_capture(
        user_id=user.id,
        capture_ref="capture-123",
    )

    assert result.id == record.id
    assert result.status == "VERIFIED"
    assert result.confidence_score == 0.98
    assert onboarding.status == "COMPLETED"
    assert onboarding.current_step == "COMPLETED"


@pytest.mark.asyncio
async def test_identity_verification_rejects_wrong_onboarding_step(
    db_session,
    user,
    monkeypatch,
):
    monkeypatch.setattr(
        identity_service,
        "get_identity_verification_provider",
        lambda: FakeIdentityProvider(),
    )

    onboarding = OnboardingRecord(
        user_id=user.id,
        status="IN_PROGRESS",
        current_step="KYC",
    )
    db_session.add(onboarding)
    await db_session.flush()

    service = IdentityVerificationService(db_session)

    with pytest.raises(ValidationError, match="not allowed"):
        await service.start(user_id=user.id)
