from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_user import AdminUser


class AdminUserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: UUID) -> AdminUser | None:
        result = await self.session.execute(
            select(AdminUser).where(AdminUser.user_id == user_id)
        )
        return result.scalar_one_or_none()
