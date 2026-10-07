from uuid import uuid4

import pytest

from app.domain.admin import AdminPermission
from app.models.admin_user import AdminUser
from app.services.admin_authorization import AdminAuthorizationService


class FakeAdminUserRepository:
    def __init__(self, admin_user=None):
        self.admin_user = admin_user

    async def get_by_user_id(self, user_id):
        return self.admin_user


@pytest.mark.asyncio
async def test_authorized_admin_can_use_permission():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="SENIOR_UNDERWRITER",
        is_active=True,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    assert await service.has_permission(
        user_id=user_id,
        permission=AdminPermission.LOAN_APPROVE,
    )

    role = await service.require_permission(
        user_id=user_id,
        permission=AdminPermission.LOAN_APPROVE,
    )

    assert role.value == "SENIOR_UNDERWRITER"


@pytest.mark.asyncio
async def test_non_admin_user_is_denied():
    user_id = uuid4()

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository()
    )

    assert not await service.has_permission(
        user_id=user_id,
        permission=AdminPermission.LOAN_APPROVE,
    )

    with pytest.raises(PermissionError, match="not an admin"):
        await service.require_permission(
            user_id=user_id,
            permission=AdminPermission.LOAN_APPROVE,
        )


@pytest.mark.asyncio
async def test_inactive_admin_is_denied():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="SENIOR_UNDERWRITER",
        is_active=False,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    assert not await service.has_permission(
        user_id=user_id,
        permission=AdminPermission.LOAN_APPROVE,
    )

    with pytest.raises(PermissionError, match="inactive"):
        await service.require_permission(
            user_id=user_id,
            permission=AdminPermission.LOAN_APPROVE,
        )


@pytest.mark.asyncio
async def test_role_without_permission_is_denied():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="UNDERWRITER",
        is_active=True,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    assert not await service.has_permission(
        user_id=user_id,
        permission=AdminPermission.LOAN_APPROVE,
    )

    with pytest.raises(PermissionError, match="does not have permission"):
        await service.require_permission(
            user_id=user_id,
            permission=AdminPermission.LOAN_APPROVE,
        )


@pytest.mark.asyncio
async def test_invalid_role_is_denied():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="NOT_A_REAL_ROLE",
        is_active=True,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    assert not await service.has_permission(
        user_id=user_id,
        permission=AdminPermission.LOAN_APPROVE,
    )

    with pytest.raises(PermissionError, match="invalid role"):
        await service.require_permission(
            user_id=user_id,
            permission=AdminPermission.LOAN_APPROVE,
        )


@pytest.mark.asyncio
async def test_kyc_reviewer_cannot_approve_loan():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="KYC_REVIEWER",
        is_active=True,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    with pytest.raises(PermissionError):
        await service.require_permission(
            user_id=user_id,
            permission=AdminPermission.LOAN_APPROVE,
        )


@pytest.mark.asyncio
async def test_finance_can_execute_disbursement():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="FINANCE",
        is_active=True,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    role = await service.require_permission(
        user_id=user_id,
        permission=AdminPermission.DISBURSEMENT_EXECUTE,
    )

    assert role.value == "FINANCE"


@pytest.mark.asyncio
async def test_finance_cannot_underwrite():
    user_id = uuid4()

    admin_user = AdminUser(
        user_id=user_id,
        role="FINANCE",
        is_active=True,
    )

    service = AdminAuthorizationService(
        admin_user_repository=FakeAdminUserRepository(admin_user)
    )

    with pytest.raises(PermissionError):
        await service.require_permission(
            user_id=user_id,
            permission=AdminPermission.UNDERWRITING_REVIEW,
        )