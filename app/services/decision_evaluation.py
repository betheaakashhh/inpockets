from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.decision import DecisionRoute
from app.models.loan_decision import LoanDecision
from app.services.decision_router import DecisionRouter
from app.services.policy_evaluation import PolicyEvaluationService


class DecisionEvaluationService:
    """Evaluate policy, route the result, and persist the decision.

    This service does not approve loans or authorize disbursement.
    The active lending workflow requires lender-admin review.
    """

    def __init__(
        self,
        *,
        policy_evaluation_service: PolicyEvaluationService,
        decision_router: DecisionRouter,
        loan_decision_repository,
    ):
        self.policy_evaluation_service = policy_evaluation_service
        self.decision_router = decision_router
        self.loan_decision_repository = loan_decision_repository

    async def evaluate(
        self,
        *,
        user_id: UUID,
        loan_application_id: UUID,
        evaluated_at: datetime,
        input_snapshot: dict[str, Any],
    ) -> LoanDecision:
        policy_evaluation = (
            await self.policy_evaluation_service.evaluate(
                user_id=user_id,
                loan_application_id=loan_application_id,
                evaluated_at=evaluated_at,
                input_snapshot=input_snapshot,
            )
        )

        decision = self.decision_router.route(
            policy_route=DecisionRoute(
                policy_evaluation.decision_route
            ),
            reasons=tuple(policy_evaluation.reasons),
            input_snapshot=dict(policy_evaluation.input_snapshot),
        )

        reason_codes = list(decision.reason_codes)

        return await self.loan_decision_repository.create(
            loan_application_id=loan_application_id,
            user_id=user_id,
            policy_evaluation_id=policy_evaluation.id,
            policy_version=policy_evaluation.policy_version,
            decision_route=decision.route.value,
            reason_codes=reason_codes,
            reasons=list(decision.reasons),
            input_snapshot=decision.input_snapshot,
            decided_at=policy_evaluation.evaluated_at,
            recommended_amount=policy_evaluation.recommended_amount,
            max_eligible_amount=policy_evaluation.max_eligible_amount,
        )