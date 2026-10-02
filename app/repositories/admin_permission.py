from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_permission import AdminPermissionRecord


class AdminPermissionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        code: str,
        name: str,
        description: str | None = None,
        is_active: bool = True,
    ) -> AdminPermissionRecord:
        permission = AdminPermissionRecord(
            code=code,
            name=name,
            description=description,
            is_active=is_active,
        )
        self.session.add(permission)
        await self.session.flush()
        return permission

    async def get_by_id(
        self,
        permission_id: UUID,
    ) -> AdminPermissionRecord | None:
        result = await self.session.execute(
            select(AdminPermissionRecord).where(
                AdminPermissionRecord.id == permission_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        code: str,
    ) -> AdminPermissionRecord | None:
        result = await self.session.execute(
            select(AdminPermissionRecord).where(
                AdminPermissionRecord.code == code
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[AdminPermissionRecord]:
        result = await self.session.execute(
            select(AdminPermissionRecord).order_by(
                AdminPermissionRecord.code.asc()
            )
        )
        return list(result.scalars().all())