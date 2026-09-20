from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingRecord
from app.models.pan_verification import PANVerification
from app.models.user import User
from app.models.user_profile import UserProfile


class AdminCustomerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_customers(self, *, offset: int, limit: int):
        result = await self.session.execute(
            select(User, UserProfile, OnboardingRecord, PANVerification)
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .outerjoin(OnboardingRecord, OnboardingRecord.user_id == User.id)
            .outerjoin(PANVerification, PANVerification.user_id == User.id)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.all()

    async def count_customers(self) -> int:
        from sqlalchemy import func

        result = await self.session.execute(select(func.count(User.id)))
        return int(result.scalar_one())

    async def get_customer(self, user_id: UUID):
        result = await self.session.execute(
            select(User, UserProfile, OnboardingRecord)
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .outerjoin(OnboardingRecord, OnboardingRecord.user_id == User.id)
            .outerjoin(PANVerification, PANVerification.user_id == User.id)
            .where(User.id == user_id)
        )
        return result.one_or_none()
