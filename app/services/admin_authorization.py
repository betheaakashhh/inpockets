from __future__ import annotations

from uuid import UUID

from app.domain.admin import AdminPermission, AdminRole
from app.repositories.admin_user import AdminUserRepository


class AdminAuthorizationService:
    """Authoritative server-side authorization for admin operations."""

    def __init__(
        self,
        *,
        admin_user_repository: AdminUserRepository,
    ):
        self.admin_user_repository = admin_user_repository

    async def get_admin_role(
        self,
        *,
        user_id: UUID,
    ) -> AdminRole:
        admin_user = await self.admin_user_repository.get_by_user_id(user_id)

        if admin_user is None:
            raise PermissionError("user is not an admin")

        if not admin_user.is_active:
            raise PermissionError("admin user is inactive")

        try:
            return AdminRole(admin_user.role)
        except ValueError as exc:
            raise PermissionError("admin user has an invalid role") from exc

    async def has_permission(
        self,
        *,
        user_id: UUID,
        permission: AdminPermission,
    ) -> bool:
        try:
            role = await self.get_admin_role(user_id=user_id)
        except PermissionError:
            return False

        return permission in self._permissions_for_role(role)

    async def require_permission(
        self,
        *,
        user_id: UUID,
        permission: AdminPermission,
    ) -> AdminRole:
        role = await self.get_admin_role(user_id=user_id)

        if permission not in self._permissions_for_role(role):
            raise PermissionError(
                f"role {role.value} does not have permission "
                f"{permission.value}"
            )

        return role

    @staticmethod
    def _permissions_for_role(
        role: AdminRole,
    ) -> frozenset[AdminPermission]:
        from app.domain.admin import ROLE_PERMISSIONS

        return ROLE_PERMISSIONS.get(role, frozenset())