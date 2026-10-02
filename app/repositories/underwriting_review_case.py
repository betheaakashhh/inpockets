from __future__ import annotations

from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.underwriting_review_case import UnderwritingReviewCase


class UnderwritingReviewCaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        status: str = "QUEUED",
        loan_decision_id: UUID | None = None,
        assigned_admin_user_id: UUID | None = None,
    ) -> UnderwritingReviewCase:
        case = UnderwritingReviewCase(
            loan_application_id=loan_application_id,
            user_id=user_id,
            loan_decision_id=loan_decision_id,
            status=status,
            assigned_admin_user_id=assigned_admin_user_id,
        )

        self.session.add(case)
        await self.session.flush()
        await self.session.refresh(case)

        return case

    async def get_by_id(
        self,
        case_id: UUID,
    ) -> UnderwritingReviewCase | None:
        result = await self.session.execute(
            select(UnderwritingReviewCase).where(
                UnderwritingReviewCase.id == case_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[UnderwritingReviewCase]:
        result = await self.session.execute(
            select(UnderwritingReviewCase)
            .where(
                UnderwritingReviewCase.loan_application_id
                == loan_application_id
            )
            .order_by(UnderwritingReviewCase.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_status(
        self,
        *,
        status: str,
    ) -> list[UnderwritingReviewCase]:
        result = await self.session.execute(
            select(UnderwritingReviewCase)
            .where(UnderwritingReviewCase.status == status)
            .order_by(UnderwritingReviewCase.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_assigned_admin(
        self,
        *,
        admin_user_id: UUID,
        status: str | None = None,
    ) -> list[UnderwritingReviewCase]:
        query = select(UnderwritingReviewCase).where(
            UnderwritingReviewCase.assigned_admin_user_id
            == admin_user_id
        )

        if status is not None:
            query = query.where(
                UnderwritingReviewCase.status == status
            )

        query = query.order_by(
            UnderwritingReviewCase.created_at.asc()
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def latest_for_loan_application(
        self,
        loan_application_id: UUID,
    ) -> UnderwritingReviewCase | None:
        result = await self.session.execute(
            select(UnderwritingReviewCase)
            .where(
                UnderwritingReviewCase.loan_application_id == loan_application_id
            )
            .order_by(
                desc(UnderwritingReviewCase.created_at),
                desc(UnderwritingReviewCase.id),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
    
    async def assign(
    self,
    *,
    case_id: UUID,
    admin_user_id: UUID,
) -> UnderwritingReviewCase | None:
        case = await self.get_by_id(case_id)

        if case is None:
            return None

        case.assigned_admin_user_id = admin_user_id
        case.status = "ASSIGNED"

        await self.session.flush()
        await self.session.refresh(case)

        return case

    async def start_review(
        self,
        *,
        case_id: UUID,
    ) -> UnderwritingReviewCase | None:
        case = await self.get_by_id(case_id)

        if case is None:
            return None

        case.status = "IN_REVIEW"

        await self.session.flush()
        await self.session.refresh(case)

        return case

    async def complete(
        self,
        *,
        case_id: UUID,
        status: str,
    ) -> UnderwritingReviewCase | None:
        case = await self.get_by_id(case_id)

        if case is None:
            return None

        if status not in {"APPROVED", "REJECTED", "CLOSED"}:
            raise ValueError("invalid terminal underwriting status")

        case.status = status
        case.closed_at = datetime.now(timezone.utc)

        await self.session.flush()
        await self.session.refresh(case)

        return case