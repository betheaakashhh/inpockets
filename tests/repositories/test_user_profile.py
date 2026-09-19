from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_profile import UserProfileRepository


@pytest.mark.asyncio
async def test_create_and_get_user_profile(db_session: AsyncSession):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = UserProfileRepository(db_session)

    profile = await repository.create(user_id=user.id)

    assert profile.id is not None
    assert profile.user_id == user.id

    fetched = await repository.get_by_user_id(user.id)

    assert fetched is not None
    assert fetched.id == profile.id
    assert fetched.user_id == user.id


@pytest.mark.asyncio
async def test_update_user_profile(db_session: AsyncSession):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = UserProfileRepository(db_session)

    profile = await repository.create(user_id=user.id)

    updated = await repository.update(
        profile,
        first_name="Aakash",
        last_name="Sahu",
        gender="MALE",
    )

    assert updated.first_name == "Aakash"
    assert updated.last_name == "Sahu"
    assert updated.gender == "MALE"