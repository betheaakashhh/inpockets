from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy_evaluation import PolicyEvaluation


class PolicyEvaluationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        policy_version_id: UUID,
        policy_version: str,
        decision_route: str,
        matched_rule_codes: list,
        reasons: list,
        input_snapshot: dict,
        evaluated_at,
        recommended_amount=None,
        max_eligible_amount=None,
    ) -> PolicyEvaluation:
        evaluation = PolicyEvaluation(
            loan_application_id=loan_application_id,
            user_id=user_id,
            policy_version_id=policy_version_id,
            policy_version=policy_version,
            decision_route=decision_route,
            matched_rule_codes=matched_rule_codes,
            reasons=reasons,
            input_snapshot=input_snapshot,
            recommended_amount=recommended_amount,
            max_eligible_amount=max_eligible_amount,
            evaluated_at=evaluated_at,
        )

        self.session.add(evaluation)
        await self.session.flush()
        await self.session.refresh(evaluation)

        return evaluation

    async def get_by_id(
        self,
        evaluation_id: UUID,
    ) -> PolicyEvaluation | None:
        result = await self.session.execute(
            select(PolicyEvaluation).where(
                PolicyEvaluation.id == evaluation_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[PolicyEvaluation]:
        result = await self.session.execute(
            select(PolicyEvaluation)
            .where(
                PolicyEvaluation.loan_application_id
                == loan_application_id
            )
            .order_by(
                PolicyEvaluation.evaluated_at.asc(),
                PolicyEvaluation.created_at.asc(),
            )
        )
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
    ) -> list[PolicyEvaluation]:
        result = await self.session.execute(
            select(PolicyEvaluation)
            .where(
                PolicyEvaluation.user_id == user_id
            )
            .order_by(
                PolicyEvaluation.evaluated_at.desc(),
                PolicyEvaluation.created_at.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_latest_for_loan_application(
        self,
        loan_application_id: UUID,
    ) -> PolicyEvaluation | None:
        result = await self.session.execute(
            select(PolicyEvaluation)
            .where(
                PolicyEvaluation.loan_application_id
                == loan_application_id
            )
            .order_by(
                PolicyEvaluation.evaluated_at.desc(),
                PolicyEvaluation.created_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()