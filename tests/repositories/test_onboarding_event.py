from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingRecord
from app.models.user import User
from app.repositories.onboarding_event import OnboardingEventRepository


@pytest.mark.asyncio
async def test_create_and_get_onboarding_events(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    onboarding = OnboardingRecord(
        user_id=user.id,
        status="NOT_STARTED",
        current_step="PROFILE",
    )
    db_session.add(onboarding)
    await db_session.flush()

    repository = OnboardingEventRepository(db_session)

    first_event = await repository.create(
        onboarding_id=onboarding.id,
        event_type="ONBOARDING_STARTED",
        event_metadata={"source": "mobile"},
    )

    second_event = await repository.create(
        onboarding_id=onboarding.id,
        event_type="PROFILE_COMPLETED",
        event_metadata={"step": "PROFILE"},
    )

    events = await repository.get_by_onboarding_id(onboarding.id)

    assert len(events) == 2

    assert events[0].id == first_event.id
    assert events[0].event_type == "ONBOARDING_STARTED"
    assert events[0].event_metadata == {"source": "mobile"}

    assert events[1].id == second_event.id
    assert events[1].event_type == "PROFILE_COMPLETED"
    assert events[1].event_metadata == {"step": "PROFILE"}


@pytest.mark.asyncio
async def test_get_events_returns_empty_for_unknown_onboarding(
    db_session: AsyncSession,
):
    repository = OnboardingEventRepository(db_session)

    events = await repository.get_by_onboarding_id(uuid4())

    assert events == []