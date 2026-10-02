import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.onboarding import OnboardingRecord
from app.models.user import User
from app.repositories.onboarding import OnboardingRepository
from app.repositories.user import UserRepository


@pytest.mark.asyncio
async def test_concurrent_user_creation_returns_one_user():
    phone_number = f"9{uuid4().int % 1_000_000_000:09d}"

    async def create_user():
        async with AsyncSessionLocal() as session:
            user = await UserRepository(session).create(phone_number=phone_number)
            await session.commit()
            return user.id

    user_ids = await asyncio.gather(create_user(), create_user())

    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(User).where(User.phone_number == phone_number)
        )

    assert count == 1
    assert user_ids[0] == user_ids[1]


@pytest.mark.asyncio
async def test_concurrent_onboarding_creation_returns_one_record():
    user_id = uuid4()

    async with AsyncSessionLocal() as session:
        session.add(User(id=user_id, phone_number=f"9{uuid4().int % 1_000_000_000:09d}"))
        await session.commit()

    async def create_onboarding():
        async with AsyncSessionLocal() as session:
            onboarding = await OnboardingRepository(session).get_or_create(user_id=user_id)
            await session.commit()
            return onboarding[0].id, onboarding[1]

    results = await asyncio.gather(create_onboarding(), create_onboarding())

    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(OnboardingRecord)
            .where(OnboardingRecord.user_id == user_id)
        )

    assert count == 1
    assert results[0][0] == results[1][0]
    assert sum(result[1] for result in results) == 1
