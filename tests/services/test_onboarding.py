from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.onboarding import OnboardingService
from app.domain.onboarding import OnboardingStatus, OnboardingStep



@pytest.mark.asyncio
async def test_get_or_create_onboarding(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    service = OnboardingService(db_session)

    onboarding = await service.get_or_create_onboarding(
        user_id=user.id,
    )

    assert onboarding.user_id == user.id
    assert onboarding.status == "NOT_STARTED"
    assert onboarding.current_step == "PROFILE"

    second = await service.get_or_create_onboarding(
        user_id=user.id,
    )

    assert second.id == onboarding.id


@pytest.mark.asyncio
async def test_get_or_create_profile(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    service = OnboardingService(db_session)

    profile = await service.get_or_create_profile(
        user_id=user.id,
    )

    assert profile.user_id == user.id

    second = await service.get_or_create_profile(
        user_id=user.id,
    )

    assert second.id == profile.id


@pytest.mark.asyncio
async def test_update_profile(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    service = OnboardingService(db_session)

    profile = await service.update_profile(
        user_id=user.id,
        first_name="Aakash",
        last_name="Sahu",
        date_of_birth=date(2000, 1, 1),
        gender="MALE",
    )

    assert profile.first_name == "Aakash"
    assert profile.last_name == "Sahu"
    assert profile.date_of_birth == date(2000, 1, 1)
    assert profile.gender == "MALE"


@pytest.mark.asyncio
async def test_update_onboarding_step_creates_event(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    service = OnboardingService(db_session)

    onboarding = await service.get_or_create_onboarding(
        user_id=user.id,
    )

    await service.update_onboarding_step(
        user_id=user.id,
        current_step="PAN",
    )

    updated = await service.update_onboarding_step(
        user_id=user.id,
        current_step="KYC",
    )

    assert updated.id == onboarding.id
    assert updated.current_step == "KYC"

    events = await service.event_repository.get_by_onboarding_id(
        onboarding.id,
    )

    assert len(events) == 3
    assert events[0].event_type == "ONBOARDING_STARTED"
    assert events[1].event_type == "ONBOARDING_STEP_CHANGED"
    assert events[1].event_metadata == {
        "from": "PROFILE",
        "to": "PAN",
    }
    assert events[2].event_type == "ONBOARDING_STEP_CHANGED"
    assert events[2].event_metadata == {
        "from": "PAN",
        "to": "KYC",
    }

@pytest.mark.asyncio
async def test_update_onboarding_step_does_not_create_duplicate_event(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    service = OnboardingService(db_session)

    onboarding = await service.get_or_create_onboarding(
        user_id=user.id,
    )

    await service.update_onboarding_step(
        user_id=user.id,
        current_step="PROFILE",
    )

    events = await service.event_repository.get_by_onboarding_id(
        onboarding.id,
    )

    assert len(events) == 1
    assert events[0].event_type == "ONBOARDING_STARTED"


@pytest.mark.asyncio
async def test_record_consent(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    service = OnboardingService(db_session)

    consent = await service.record_consent(
        user_id=user.id,
        consent_type="PRIVACY_POLICY",
        version="1.0",
        status="GRANTED",
    )

    assert consent.user_id == user.id
    assert consent.consent_type == "PRIVACY_POLICY"
    assert consent.version == "1.0"
    assert consent.status == "GRANTED"

@pytest.mark.asyncio
async def test_update_onboarding_step_moves_forward(db_session, user):
    service = OnboardingService(db_session)

    onboarding = await service.get_or_create_onboarding(
        user_id=user.id,
    )

    updated = await service.update_onboarding_step(
        user_id=user.id,
        current_step=OnboardingStep.PAN.value,
    )

    assert updated.id == onboarding.id
    assert updated.current_step == OnboardingStep.PAN.value
    assert updated.status == OnboardingStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_update_onboarding_step_rejects_skipping(db_session, user):
    service = OnboardingService(db_session)

    await service.get_or_create_onboarding(
        user_id=user.id,
    )

    with pytest.raises(ValueError, match="Invalid onboarding step transition"):
        await service.update_onboarding_step(
            user_id=user.id,
            current_step=OnboardingStep.KYC.value,
        )


@pytest.mark.asyncio
async def test_update_onboarding_step_rejects_backward_transition(
    db_session,
    user,
):
    service = OnboardingService(db_session)

    await service.get_or_create_onboarding(
        user_id=user.id,
    )

    await service.update_onboarding_step(
        user_id=user.id,
        current_step=OnboardingStep.PAN.value,
    )

    with pytest.raises(ValueError, match="Invalid onboarding step transition"):
        await service.update_onboarding_step(
            user_id=user.id,
            current_step=OnboardingStep.PROFILE.value,
        )


@pytest.mark.asyncio
async def test_update_onboarding_step_completes_onboarding(
    db_session,
    user,
):
    service = OnboardingService(db_session)

    await service.get_or_create_onboarding(
        user_id=user.id,
    )

    await service.update_onboarding_step(
        user_id=user.id,
        current_step=OnboardingStep.PAN.value,
    )
    await service.update_onboarding_step(
        user_id=user.id,
        current_step=OnboardingStep.KYC.value,
    )
    await service.update_onboarding_step(
        user_id=user.id,
        current_step=OnboardingStep.IDENTITY.value,
    )

    onboarding = await service.update_onboarding_step(
        user_id=user.id,
        current_step=OnboardingStep.COMPLETED.value,
    )

    assert onboarding.current_step == OnboardingStep.COMPLETED.value
    assert onboarding.status == OnboardingStatus.COMPLETED.value