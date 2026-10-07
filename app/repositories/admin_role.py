from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_role import AdminRoleRecord


class AdminRoleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        code: str,
        name: str,
        description: str | None = None,
        is_active: bool = True,
    ) -> AdminRoleRecord:
        role = AdminRoleRecord(
            code=code,
            name=name,
            description=description,
            is_active=is_active,
        )
        self.session.add(role)
        await self.session.flush()
        return role

    async def get_by_id(self, role_id: UUID) -> AdminRoleRecord | None:
        result = await self.session.execute(
            select(AdminRoleRecord).where(AdminRoleRecord.id == role_id)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> AdminRoleRecord | None:
        result = await self.session.execute(
            select(AdminRoleRecord).where(AdminRoleRecord.code == code)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[AdminRoleRecord]:
        result = await self.session.execute(
            select(AdminRoleRecord).order_by(
                AdminRoleRecord.code.asc()
            )
        )
        return list(result.scalars().all())