from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.policy_version import PolicyVersionRepository


@pytest.mark.asyncio
async def test_create_policy_version(db_session):
    repository = PolicyVersionRepository(db_session)

    effective_from = datetime.now(timezone.utc)

    policy_version = await repository.create(
        version="policy-v1",
        effective_from=effective_from,
    )

    assert policy_version.id is not None
    assert policy_version.version == "policy-v1"
    assert policy_version.effective_from == effective_from
    assert policy_version.effective_to is None

    await db_session.commit()


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    repository = PolicyVersionRepository(db_session)

    policy_version = await repository.create(
        version="policy-v1",
        effective_from=datetime.now(timezone.utc),
    )

    result = await repository.get_by_id(policy_version.id)

    assert result is not None
    assert result.id == policy_version.id
    assert result.version == "policy-v1"


@pytest.mark.asyncio
async def test_get_by_version(db_session):
    repository = PolicyVersionRepository(db_session)

    policy_version = await repository.create(
        version="policy-v2",
        effective_from=datetime.now(timezone.utc),
    )

    result = await repository.get_by_version("policy-v2")

    assert result is not None
    assert result.id == policy_version.id
    assert result.version == "policy-v2"


@pytest.mark.asyncio
async def test_list_all_orders_by_effective_from(db_session):
    repository = PolicyVersionRepository(db_session)

    now = datetime.now(timezone.utc)

    await repository.create(
        version="policy-v2",
        effective_from=now + timedelta(days=1),
    )

    await repository.create(
        version="policy-v1",
        effective_from=now,
    )

    results = await repository.list_all()

    assert [item.version for item in results] == [
        "policy-v1",
        "policy-v2",
    ]


@pytest.mark.asyncio
async def test_get_effective_at_selects_active_policy(db_session):
    repository = PolicyVersionRepository(db_session)

    now = datetime.now(timezone.utc)

    await repository.create(
        version="policy-v1",
        effective_from=now - timedelta(days=30),
        effective_to=now - timedelta(days=1),
    )

    active = await repository.create(
        version="policy-v2",
        effective_from=now - timedelta(hours=1),
    )

    result = await repository.get_effective_at(now)

    assert result is not None
    assert result.id == active.id
    assert result.version == "policy-v2"


@pytest.mark.asyncio
async def test_get_effective_at_ignores_future_policy(db_session):
    repository = PolicyVersionRepository(db_session)

    now = datetime.now(timezone.utc)

    current = await repository.create(
        version="policy-current",
        effective_from=now - timedelta(days=1),
    )

    await repository.create(
        version="policy-future",
        effective_from=now + timedelta(days=1),
    )

    result = await repository.get_effective_at(now)

    assert result is not None
    assert result.id == current.id
    assert result.version == "policy-current"


@pytest.mark.asyncio
async def test_get_effective_at_returns_none_when_no_policy_is_active(
    db_session,
):
    repository = PolicyVersionRepository(db_session)

    now = datetime.now(timezone.utc)

    await repository.create(
        version="policy-future",
        effective_from=now + timedelta(days=1),
    )

    result = await repository.get_effective_at(now)

    assert result is None