from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.policy_evaluation import PolicyEvaluation
from app.repositories.policy_evaluation import PolicyEvaluationRepository
from app.repositories.policy_rule import PolicyRuleRepository
from app.services.policy_engine import PolicyEngine
from app.services.policy_version_selector import PolicyVersionSelector


class PolicyEvaluationService:
    """Select, evaluate, and persist a versioned policy evaluation."""

    def __init__(
        self,
        *,
        policy_version_selector: PolicyVersionSelector,
        policy_rule_repository: PolicyRuleRepository,
        policy_evaluation_repository: PolicyEvaluationRepository,
        policy_engine: PolicyEngine,
    ):
        self.policy_version_selector = policy_version_selector
        self.policy_rule_repository = policy_rule_repository
        self.policy_evaluation_repository = policy_evaluation_repository
        self.policy_engine = policy_engine

    async def evaluate(
        self,
        *,
        user_id: UUID,
        loan_application_id: UUID,
        evaluated_at: datetime,
        input_snapshot: dict[str, Any],
    ) -> PolicyEvaluation:
        policy_version = await self.policy_version_selector.select(
            evaluated_at=evaluated_at,
        )

        rules = await self.policy_rule_repository.list_by_policy_version(
            policy_version.id,
        )

        if not rules:
            raise ValueError(
                f"policy version {policy_version.version} has no rules"
            )

        domain_rules = tuple(
            self._to_domain_rule(rule)
            for rule in rules
        )

        evaluation = self.policy_engine.evaluate(
            policy_version=self._to_domain_policy_version(
                policy_version,
                domain_rules,
            ),
            rules=domain_rules,
            input_snapshot=input_snapshot,
            evaluated_at=evaluated_at,
            user_id=user_id,
            loan_application_id=loan_application_id,
        )

        return await self.policy_evaluation_repository.create(
            loan_application_id=loan_application_id,
            user_id=user_id,
            policy_version_id=policy_version.id,
            policy_version=policy_version.version,
            decision_route=evaluation.decision_route.value,
            matched_rule_codes=list(evaluation.matched_rule_codes),
            reasons=list(evaluation.reasons),
            input_snapshot=evaluation.input_snapshot,
            evaluated_at=evaluation.evaluated_at,
            recommended_amount=evaluation.recommended_amount,
            max_eligible_amount=evaluation.max_eligible_amount,
        )

    @staticmethod
    def _to_domain_rule(rule):
        from app.domain.policy import PolicyRule, PolicyRuleEffect

        return PolicyRule(
            code=rule.code,
            order=rule.rule_order,
            effect=PolicyRuleEffect(rule.effect),
            condition=rule.condition,
            reason_code=rule.reason_code,
            description=rule.description,
        )

    @staticmethod
    def _to_domain_policy_version(
        policy_version,
        rules,
    ):
        from app.domain.policy import PolicyVersion

        return PolicyVersion(
            version=policy_version.version,
            rules=rules,
            effective_from=policy_version.effective_from,
            effective_to=policy_version.effective_to,
        )