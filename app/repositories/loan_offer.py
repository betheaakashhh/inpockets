
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_offer import LoanOffer


class LoanOfferRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: uuid.UUID,
        user_id: uuid.UUID,
        version: int,
        principal_amount: Decimal,
        tenure_days: int,
        commercial_terms: dict,
        created_by_admin_user_id: uuid.UUID | None = None,
    ) -> LoanOffer:
        offer = LoanOffer(
            loan_application_id=loan_application_id,
            user_id=user_id,
            version=version,
            principal_amount=principal_amount,
            tenure_days=tenure_days,
            commercial_terms=commercial_terms,
            status="DRAFT",
            created_by_admin_user_id=created_by_admin_user_id,
        )
        self.session.add(offer)
        await self.session.flush()
        await self.session.refresh(offer)
        return offer

    async def get_by_id(
        self,
        *,
        offer_id: uuid.UUID,
    ) -> LoanOffer | None:
        result = await self.session.execute(
            select(LoanOffer).where(LoanOffer.id == offer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(
        self,
        *,
        offer_id: uuid.UUID,
    ) -> LoanOffer | None:
        result = await self.session.execute(
            select(LoanOffer)
            .where(LoanOffer.id == offer_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_by_application_id(
        self,
        *,
        loan_application_id: uuid.UUID,
    ) -> list[LoanOffer]:
        result = await self.session.execute(
            select(LoanOffer)
            .where(LoanOffer.loan_application_id == loan_application_id)
            .order_by(LoanOffer.version.desc())
        )
        return list(result.scalars().all())

    async def list_by_user_id(
        self,
        *,
        user_id: uuid.UUID,
    ) -> list[LoanOffer]:
        result = await self.session.execute(
            select(LoanOffer)
            .where(LoanOffer.user_id == user_id)
            .order_by(LoanOffer.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest_for_application(
        self,
        *,
        loan_application_id: uuid.UUID,
    ) -> LoanOffer | None:
        result = await self.session.execute(
            select(LoanOffer)
            .where(LoanOffer.loan_application_id == loan_application_id)
            .order_by(LoanOffer.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_application_for_update(
        self,
        *,
        loan_application_id: uuid.UUID,
    ) -> LoanOffer | None:
        result = await self.session.execute(
            select(LoanOffer)
            .where(LoanOffer.loan_application_id == loan_application_id)
            .order_by(LoanOffer.version.desc())
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def update(self, offer: LoanOffer) -> LoanOffer:
        await self.session.flush()
        await self.session.refresh(offer)
        return offer

    async def get_accepted_for_application(
        self,
        *,
        loan_application_id: uuid.UUID,
    ) -> LoanOffer | None:
        result = await self.session.execute(
            select(LoanOffer)
            .where(
                LoanOffer.loan_application_id == loan_application_id,
                LoanOffer.status == "ACCEPTED",
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_open_for_application_for_update(
        self,
        *,
        loan_application_id: uuid.UUID,
    ) -> list[LoanOffer]:
        """Live (ISSUED/ACCEPTED) offers for an application, row-locked."""
        result = await self.session.execute(
            select(LoanOffer)
            .where(
                LoanOffer.loan_application_id == loan_application_id,
                LoanOffer.status.in_(("ISSUED", "ACCEPTED")),
            )
            .order_by(LoanOffer.version.asc())
            .with_for_update()
        )
        return list(result.scalars().all())

    async def list_due_for_expiry_for_update(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[LoanOffer]:
        """ISSUED offers past expiry. SKIP LOCKED so workers never collide."""
        result = await self.session.execute(
            select(LoanOffer)
            .where(
                LoanOffer.status == "ISSUED",
                LoanOffer.expires_at.is_not(None),
                LoanOffer.expires_at <= now,
            )
            .order_by(LoanOffer.expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())
