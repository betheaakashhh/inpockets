from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.policy_version import PolicyVersion
from app.repositories.policy_version import PolicyVersionRepository
from app.services.policy_version_selector import PolicyVersionSelector


async def create_policy(
    db_session,
    *,
    version: str,
    effective_from: datetime,
    effective_to: datetime | None = None,
) -> PolicyVersion:
    repository = PolicyVersionRepository(db_session)

    return await repository.create(
        version=version,
        effective_from=effective_from,
        effective_to=effective_to,
    )


@pytest.mark.asyncio
async def test_selects_policy_effective_at_evaluation_time(db_session):
    repository = PolicyVersionRepository(db_session)

    effective_from = datetime(2026, 1, 1, tzinfo=timezone.utc)

    policy = await repository.create(
        version="policy-v1",
        effective_from=effective_from,
    )

    selector = PolicyVersionSelector(repository)

    selected = await selector.select(
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )

    assert selected.id == policy.id
    assert selected.version == "policy-v1"


@pytest.mark.asyncio
async def test_does_not_select_future_policy(db_session):
    repository = PolicyVersionRepository(db_session)

    await repository.create(
        version="future-policy",
        effective_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )

    selector = PolicyVersionSelector(repository)

    with pytest.raises(
        ValueError,
        match="no effective policy version",
    ):
        await selector.select(
            evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_does_not_select_expired_policy(db_session):
    repository = PolicyVersionRepository(db_session)

    await repository.create(
        version="expired-policy",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    selector = PolicyVersionSelector(repository)

    with pytest.raises(
        ValueError,
        match="no effective policy version",
    ):
        await selector.select(
            evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_selects_newer_effective_policy_version(db_session):
    repository = PolicyVersionRepository(db_session)

    old_policy = await repository.create(
        version="policy-v1",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    new_policy = await repository.create(
        version="policy-v2",
        effective_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    selector = PolicyVersionSelector(repository)

    selected = await selector.select(
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )

    assert selected.id == new_policy.id
    assert selected.version == "policy-v2"
    assert selected.id != old_policy.id


@pytest.mark.asyncio
async def test_effective_from_is_inclusive(db_session):
    repository = PolicyVersionRepository(db_session)

    policy = await repository.create(
        version="policy-v1",
        effective_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
        effective_to=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    selector = PolicyVersionSelector(repository)

    selected = await selector.select(
        evaluated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert selected.id == policy.id


@pytest.mark.asyncio
async def test_effective_to_is_exclusive(db_session):
    repository = PolicyVersionRepository(db_session)

    old_policy = await repository.create(
        version="policy-v1",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    new_policy = await repository.create(
        version="policy-v2",
        effective_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    selector = PolicyVersionSelector(repository)

    selected = await selector.select(
        evaluated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert selected.id == new_policy.id
    assert selected.id != old_policy.id