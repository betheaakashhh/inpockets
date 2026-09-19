from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_profile import UserProfile


class UserProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(
        self,
        user_id: UUID,
    ) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: UUID,
    ) -> UserProfile:
        profile = UserProfile(user_id=user_id)

        self.session.add(profile)

        await self.session.flush()

        return profile

    async def update(
        self,
        profile: UserProfile,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        date_of_birth=None,
        gender: str | None = None,
    ) -> UserProfile:
        if first_name is not None:
            profile.first_name = first_name

        if last_name is not None:
            profile.last_name = last_name

        if date_of_birth is not None:
            profile.date_of_birth = date_of_birth

        if gender is not None:
            profile.gender = gender

        await self.session.flush()

        return profile