from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_decision import LoanDecision


class LoanDecisionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        policy_evaluation_id: UUID,
        policy_version: str,
        decision_route: str,
        reason_codes: list[str],
        reasons: list[str],
        input_snapshot: dict,
        decided_at: datetime,
        recommended_amount=None,
        max_eligible_amount=None,
    ) -> LoanDecision:
        decision = LoanDecision(
            loan_application_id=loan_application_id,
            user_id=user_id,
            policy_evaluation_id=policy_evaluation_id,
            policy_version=policy_version,
            decision_route=decision_route,
            reason_codes=reason_codes,
            reasons=reasons,
            input_snapshot=input_snapshot,
            recommended_amount=recommended_amount,
            max_eligible_amount=max_eligible_amount,
            decided_at=decided_at,
        )

        self.session.add(decision)
        await self.session.flush()

        return decision

    async def get_by_id(
        self,
        decision_id: UUID,
    ) -> LoanDecision | None:
        result = await self.session.execute(
            select(LoanDecision).where(
                LoanDecision.id == decision_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[LoanDecision]:
        result = await self.session.execute(
            select(LoanDecision)
            .where(
                LoanDecision.loan_application_id
                == loan_application_id
            )
            .order_by(
                LoanDecision.decided_at.asc(),
                LoanDecision.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
    ) -> list[LoanDecision]:
        result = await self.session.execute(
            select(LoanDecision)
            .where(LoanDecision.user_id == user_id)
            .order_by(
                LoanDecision.decided_at.asc(),
                LoanDecision.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_latest_for_loan_application(
        self,
        loan_application_id: UUID,
    ) -> LoanDecision | None:
        result = await self.session.execute(
            select(LoanDecision)
            .where(
                LoanDecision.loan_application_id
                == loan_application_id
            )
            .order_by(
                LoanDecision.decided_at.desc(),
                LoanDecision.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()