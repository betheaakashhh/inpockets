from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingRecord
from app.models.user import User
from app.repositories.onboarding import OnboardingRepository


@pytest.mark.asyncio
async def test_create_and_get_onboarding(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = OnboardingRepository(db_session)

    onboarding = await repository.create(user_id=user.id)

    assert onboarding.id is not None
    assert onboarding.user_id == user.id
    assert onboarding.status == "NOT_STARTED"
    assert onboarding.current_step == "PROFILE"

    fetched = await repository.get_by_user_id(user.id)

    assert fetched is not None
    assert fetched.id == onboarding.id
    assert fetched.user_id == user.id


@pytest.mark.asyncio
async def test_update_onboarding(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = OnboardingRepository(db_session)

    onboarding = await repository.create(user_id=user.id)

    updated = await repository.update(
        onboarding,
        status="IN_PROGRESS",
        current_step="KYC",
    )

    assert updated.status == "IN_PROGRESS"
    assert updated.current_step == "KYC"


@pytest.mark.asyncio
async def test_get_onboarding_returns_none_for_unknown_user(
    db_session: AsyncSession,
):
    repository = OnboardingRepository(db_session)

    result = await repository.get_by_user_id(uuid4())

    assert result is None