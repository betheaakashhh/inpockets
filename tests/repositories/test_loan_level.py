from decimal import Decimal

import pytest

from app.repositories.loan_level import LoanLevelRepository


@pytest.mark.asyncio
async def test_create_and_get_by_id(db_session):
    repository = LoanLevelRepository(db_session)

    created = await repository.create(
        code="LEVEL_1",
        name="Starter",
        min_amount=Decimal("1000"),
        max_amount=Decimal("10000"),
        min_tenure_days=7,
        max_tenure_days=30,
        description="Starter lending level",
    )

    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.code == "LEVEL_1"
    assert fetched.min_amount == Decimal("1000.00")
    assert fetched.max_amount == Decimal("10000.00")


@pytest.mark.asyncio
async def test_get_by_code(db_session):
    repository = LoanLevelRepository(db_session)

    created = await repository.create(
        code="LEVEL_2",
        name="Standard",
        min_amount=Decimal("5000"),
        max_amount=Decimal("25000"),
        min_tenure_days=15,
        max_tenure_days=60,
    )

    fetched = await repository.get_by_code("LEVEL_2")

    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_list_all_is_deterministic(db_session):
    repository = LoanLevelRepository(db_session)

    await repository.create(
        code="LEVEL_2",
        name="Standard",
        min_amount=Decimal("5000"),
        max_amount=Decimal("25000"),
        min_tenure_days=15,
        max_tenure_days=60,
    )

    await repository.create(
        code="LEVEL_1",
        name="Starter",
        min_amount=Decimal("1000"),
        max_amount=Decimal("10000"),
        min_tenure_days=7,
        max_tenure_days=30,
    )

    levels = await repository.list_all()

    assert [level.code for level in levels] == [
        "LEVEL_1",
        "LEVEL_2",
    ]