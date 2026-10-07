from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_role_permission import AdminRolePermission


class AdminRolePermissionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        role_id: UUID,
        permission_id: UUID,
    ) -> AdminRolePermission:
        assignment = AdminRolePermission(
            role_id=role_id,
            permission_id=permission_id,
        )
        self.session.add(assignment)
        await self.session.flush()
        return assignment

    async def get_by_id(
        self,
        assignment_id: UUID,
    ) -> AdminRolePermission | None:
        result = await self.session.execute(
            select(AdminRolePermission).where(
                AdminRolePermission.id == assignment_id
            )
        )
        return result.scalar_one_or_none()

    async def get_assignment(
        self,
        *,
        role_id: UUID,
        permission_id: UUID,
    ) -> AdminRolePermission | None:
        result = await self.session.execute(
            select(AdminRolePermission).where(
                AdminRolePermission.role_id == role_id,
                AdminRolePermission.permission_id == permission_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_role(
        self,
        role_id: UUID,
    ) -> list[AdminRolePermission]:
        result = await self.session.execute(
            select(AdminRolePermission)
            .where(AdminRolePermission.role_id == role_id)
            .order_by(AdminRolePermission.permission_id.asc())
        )
        return list(result.scalars().all())

    async def list_by_permission(
        self,
        permission_id: UUID,
    ) -> list[AdminRolePermission]:
        result = await self.session.execute(
            select(AdminRolePermission)
            .where(AdminRolePermission.permission_id == permission_id)
            .order_by(AdminRolePermission.role_id.asc())
        )
        return list(result.scalars().all())