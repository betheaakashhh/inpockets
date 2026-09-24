import uuid

from sqlalchemy import select #type: ignore
from sqlalchemy.ext.asyncio import AsyncSession #type: ignore

from app.models.loan_application import LoanApplication, LoanApplicationEvent


class LoanApplicationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        application_number: str,
        user_id: uuid.UUID,
        status: str,
        requested_amount,
        requested_tenure_days: int,
    ) -> LoanApplication:
        application = LoanApplication(
            application_number=application_number,
            user_id=user_id,
            status=status,
            requested_amount=requested_amount,
            requested_tenure_days=requested_tenure_days,
        )

        self.session.add(application)
        await self.session.flush()
        await self.session.refresh(application)

        return application

    async def get_by_id(
        self,
        *,
        application_id: uuid.UUID,
    ) -> LoanApplication | None:
        result = await self.session.execute(
            select(LoanApplication).where(
                LoanApplication.id == application_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(
        self,
        *,
        application_id: uuid.UUID,
    ) -> LoanApplication | None:
        """Load an application while holding a database row lock."""
        result = await self.session.execute(
            select(LoanApplication)
            .where(LoanApplication.id == application_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_application_number(
        self,
        *,
        application_number: str,
    ) -> LoanApplication | None:
        result = await self.session.execute(
            select(LoanApplication).where(
                LoanApplication.application_number == application_number,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user_id(
        self,
        *,
        user_id: uuid.UUID,
    ) -> list[LoanApplication]:
        result = await self.session.execute(
            select(LoanApplication)
            .where(LoanApplication.user_id == user_id)
            .order_by(LoanApplication.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(
        self,
        application: LoanApplication,
    ) -> LoanApplication:
        await self.session.flush()
        await self.session.refresh(application)

        return application

    async def create_event(
        self,
        *,
        application_id: uuid.UUID,
        event_type: str,
        previous_status: str | None,
        new_status: str,
        actor_type: str,
        actor_id: uuid.UUID | None = None,
        reason: str | None = None,
        event_metadata: dict | None = None,
    ) -> LoanApplicationEvent:
        event = LoanApplicationEvent(
            application_id=application_id,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            event_metadata=event_metadata,
        )

        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)

        return event

    async def list_events(
        self,
        *,
        application_id: uuid.UUID,
    ) -> list[LoanApplicationEvent]:
        result = await self.session.execute(
            select(LoanApplicationEvent)
            .where(
                LoanApplicationEvent.application_id == application_id,
            )
            .order_by(LoanApplicationEvent.created_at.asc())
        )
        return list(result.scalars().all())