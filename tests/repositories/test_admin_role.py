import pytest

from app.repositories.admin_role import AdminRoleRepository


@pytest.mark.asyncio
async def test_create_and_get_by_code(db_session):
    repository = AdminRoleRepository(db_session)

    role = await repository.create(
        code="UNDERWRITER",
        name="Underwriter",
        description="Loan underwriting reviewer",
    )

    found = await repository.get_by_code("UNDERWRITER")

    assert found is not None
    assert found.id == role.id
    assert found.code == "UNDERWRITER"
    assert found.name == "Underwriter"


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    repository = AdminRoleRepository(db_session)

    role = await repository.create(
        code="KYC_REVIEWER",
        name="KYC Reviewer",
    )

    found = await repository.get_by_id(role.id)

    assert found is not None
    assert found.id == role.id


@pytest.mark.asyncio
async def test_list_all(db_session):
    repository = AdminRoleRepository(db_session)

    await repository.create(
        code="UNDERWRITER",
        name="Underwriter",
    )
    await repository.create(
        code="KYC_REVIEWER",
        name="KYC Reviewer",
    )

    roles = await repository.list_all()

    assert [role.code for role in roles] == [
        "KYC_REVIEWER",
        "UNDERWRITER",
    ]