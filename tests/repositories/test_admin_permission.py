import pytest

from app.repositories.admin_permission import AdminPermissionRepository


@pytest.mark.asyncio
async def test_create_and_get_by_code(db_session):
    repository = AdminPermissionRepository(db_session)

    permission = await repository.create(
        code="LOAN_APPROVE",
        name="Approve Loan",
        description="Approve a manually reviewed loan",
    )

    found = await repository.get_by_code("LOAN_APPROVE")

    assert found is not None
    assert found.id == permission.id
    assert found.code == "LOAN_APPROVE"
    assert found.name == "Approve Loan"


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    repository = AdminPermissionRepository(db_session)

    permission = await repository.create(
        code="KYC_REVIEW",
        name="Review KYC",
    )

    found = await repository.get_by_id(permission.id)

    assert found is not None
    assert found.id == permission.id


@pytest.mark.asyncio
async def test_list_all(db_session):
    repository = AdminPermissionRepository(db_session)

    await repository.create(
        code="LOAN_APPROVE",
        name="Approve Loan",
    )
    await repository.create(
        code="KYC_REVIEW",
        name="Review KYC",
    )

    permissions = await repository.list_all()

    assert [permission.code for permission in permissions] == [
        "KYC_REVIEW",
        "LOAN_APPROVE",
    ]