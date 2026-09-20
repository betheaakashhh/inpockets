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

    def _pan_status_subquery(self):
        return (
            select(PANVerification.status)
            .where(PANVerification.user_id == User.id)
            .order_by(PANVerification.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )

    def _pan_masked_subquery(self):
        return (
            select(PANVerification.pan_number_masked)
            .where(PANVerification.user_id == User.id)
            .order_by(PANVerification.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )

    async def list_customers(self, *, offset: int, limit: int):
        result = await self.session.execute(
            select(
                User,
                UserProfile,
                OnboardingRecord,
                self._pan_status_subquery().label("pan_status"),
                self._pan_masked_subquery().label("pan_number_masked"),
            )
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .outerjoin(OnboardingRecord, OnboardingRecord.user_id == User.id)
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
            select(
                User,
                UserProfile,
                OnboardingRecord,
                self._pan_status_subquery().label("pan_status"),
                self._pan_masked_subquery().label("pan_number_masked"),
            )
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .outerjoin(OnboardingRecord, OnboardingRecord.user_id == User.id)
            .where(User.id == user_id)
        )
        return result.one_or_none()
