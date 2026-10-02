import pytest

from app.repositories.admin_permission import AdminPermissionRepository
from app.repositories.admin_role import AdminRoleRepository
from app.repositories.admin_role_permission import (
    AdminRolePermissionRepository,
)


@pytest.mark.asyncio
async def test_create_and_get_assignment(db_session):
    role_repository = AdminRoleRepository(db_session)
    permission_repository = AdminPermissionRepository(db_session)
    assignment_repository = AdminRolePermissionRepository(db_session)

    role = await role_repository.create(
        code="UNDERWRITER",
        name="Underwriter",
    )

    permission = await permission_repository.create(
        code="UNDERWRITING_REVIEW",
        name="Underwriting Review",
    )

    assignment = await assignment_repository.create(
        role_id=role.id,
        permission_id=permission.id,
    )

    found = await assignment_repository.get_assignment(
        role_id=role.id,
        permission_id=permission.id,
    )

    assert found is not None
    assert found.id == assignment.id
    assert found.role_id == role.id
    assert found.permission_id == permission.id


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    role_repository = AdminRoleRepository(db_session)
    permission_repository = AdminPermissionRepository(db_session)
    assignment_repository = AdminRolePermissionRepository(db_session)

    role = await role_repository.create(
        code="KYC_REVIEWER",
        name="KYC Reviewer",
    )

    permission = await permission_repository.create(
        code="KYC_REVIEW",
        name="KYC Review",
    )

    assignment = await assignment_repository.create(
        role_id=role.id,
        permission_id=permission.id,
    )

    found = await assignment_repository.get_by_id(assignment.id)

    assert found is not None
    assert found.id == assignment.id


@pytest.mark.asyncio
async def test_list_by_role(db_session):
    role_repository = AdminRoleRepository(db_session)
    permission_repository = AdminPermissionRepository(db_session)
    assignment_repository = AdminRolePermissionRepository(db_session)

    role = await role_repository.create(
        code="UNDERWRITER",
        name="Underwriter",
    )

    permission_one = await permission_repository.create(
        code="LOAN_APPLICATION_READ",
        name="Loan Application Read",
    )
    permission_two = await permission_repository.create(
        code="UNDERWRITING_REVIEW",
        name="Underwriting Review",
    )

    await assignment_repository.create(
        role_id=role.id,
        permission_id=permission_one.id,
    )
    await assignment_repository.create(
        role_id=role.id,
        permission_id=permission_two.id,
    )

    assignments = await assignment_repository.list_by_role(role.id)

    assert len(assignments) == 2
    assert {
        assignment.permission_id
        for assignment in assignments
    } == {
        permission_one.id,
        permission_two.id,
    }


@pytest.mark.asyncio
async def test_list_by_permission(db_session):
    role_repository = AdminRoleRepository(db_session)
    permission_repository = AdminPermissionRepository(db_session)
    assignment_repository = AdminRolePermissionRepository(db_session)

    role_one = await role_repository.create(
        code="UNDERWRITER",
        name="Underwriter",
    )
    role_two = await role_repository.create(
        code="SENIOR_UNDERWRITER",
        name="Senior Underwriter",
    )

    permission = await permission_repository.create(
        code="LOAN_APPLICATION_READ",
        name="Loan Application Read",
    )

    await assignment_repository.create(
        role_id=role_one.id,
        permission_id=permission.id,
    )
    await assignment_repository.create(
        role_id=role_two.id,
        permission_id=permission.id,
    )

    assignments = await assignment_repository.list_by_permission(
        permission.id
    )

    assert len(assignments) == 2
    assert {
        assignment.role_id
        for assignment in assignments
    } == {
        role_one.id,
        role_two.id,
    }


@pytest.mark.asyncio
async def test_duplicate_assignment_is_rejected(db_session):
    role_repository = AdminRoleRepository(db_session)
    permission_repository = AdminPermissionRepository(db_session)
    assignment_repository = AdminRolePermissionRepository(db_session)

    role = await role_repository.create(
        code="UNDERWRITER",
        name="Underwriter",
    )

    permission = await permission_repository.create(
        code="UNDERWRITING_REVIEW",
        name="Underwriting Review",
    )

    await assignment_repository.create(
        role_id=role.id,
        permission_id=permission.id,
    )

    with pytest.raises(Exception):
        await assignment_repository.create(
            role_id=role.id,
            permission_id=permission.id,
        )