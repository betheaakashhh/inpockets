from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.consent import ConsentRepository


@pytest.mark.asyncio
async def test_create_and_get_consent(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = ConsentRepository(db_session)

    consent = await repository.create(
        user_id=user.id,
        consent_type="PRIVACY_POLICY",
        version="1.0",
        status="GRANTED",
    )

    assert consent.id is not None
    assert consent.user_id == user.id
    assert consent.consent_type == "PRIVACY_POLICY"
    assert consent.version == "1.0"
    assert consent.status == "GRANTED"

    consents = await repository.get_by_user_id(user.id)

    assert len(consents) == 1
    assert consents[0].id == consent.id


@pytest.mark.asyncio
async def test_get_consent_by_user_and_type(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = ConsentRepository(db_session)

    consent = await repository.create(
        user_id=user.id,
        consent_type="TERMS",
        version="1.0",
        status="GRANTED",
    )

    fetched = await repository.get_by_user_and_type(
        user.id,
        "TERMS",
    )

    assert fetched is not None
    assert fetched.id == consent.id


@pytest.mark.asyncio
async def test_get_consent_returns_none_for_unknown_type(
    db_session: AsyncSession,
):
    user = User(phone_number=f"+9199{uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()

    repository = ConsentRepository(db_session)

    result = await repository.get_by_user_and_type(
        user.id,
        "UNKNOWN",
    )

    assert result is None