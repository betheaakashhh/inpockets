from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.policy import (
    DecisionRoute,
    PolicyEvaluation,
    PolicyRule,
    PolicyRuleEffect,
    PolicyVersion,
)


class PolicyEngine:
    """Deterministic policy evaluation engine.

    The policy engine evaluates configured policy rules against an immutable
    input snapshot. It does not perform risk scoring and does not directly
    approve or disburse loans.
    """

    def evaluate(
        self,
        *,
        policy_version: PolicyVersion,
        rules: tuple[PolicyRule, ...],
        input_snapshot: dict[str, Any],
        evaluated_at: datetime,
        user_id: UUID,
        loan_application_id: UUID,
    ) -> PolicyEvaluation:
        if not input_snapshot:
            raise ValueError("input_snapshot is required")

        if not rules:
            raise ValueError("at least one policy rule is required")

        ordered_rules = tuple(
            sorted(
                rules,
                key=lambda rule: (rule.order, rule.code),
            )
        )

        matched_rule_codes: list[str] = []
        reasons: list[str] = []

        decision_route = DecisionRoute.MANUAL_REVIEW

        recommended_amount = self._decimal_or_none(
            input_snapshot.get("recommended_amount")
        )
        max_eligible_amount = self._decimal_or_none(
            input_snapshot.get("max_eligible_amount")
        )

        for rule in ordered_rules:
            if not self._matches(rule, input_snapshot):
                continue

            matched_rule_codes.append(rule.code)

            if rule.reason_code:
                reasons.append(rule.reason_code)
            elif rule.description:
                reasons.append(rule.description)

            decision_route = self._route_for_effect(
                rule.effect,
                current_route=decision_route,
            )

            # A terminal route stops further conflicting rules from changing
            # the result. Rule ordering is therefore deterministic.
            if decision_route in {
                DecisionRoute.AUTO_REJECTED,
                DecisionRoute.PENDING_ADDITIONAL_INFORMATION,
                DecisionRoute.PENDING_EXTERNAL_PROVIDER,
                DecisionRoute.ERROR_REQUIRES_REVIEW,
            }:
                break

        # InPockets lending does not automatically approve applications.
        # If no blocking/pending condition was produced, the application
        # proceeds to lender-admin manual review.
        if decision_route == DecisionRoute.AUTO_APPROVED:
            decision_route = DecisionRoute.MANUAL_REVIEW

        return PolicyEvaluation(
            id=UUID(int=0),
            user_id=user_id,
            loan_application_id=loan_application_id,
            policy_version=policy_version.version,
            evaluated_at=evaluated_at,
            decision_route=decision_route,
            matched_rule_codes=tuple(matched_rule_codes),
            reasons=tuple(reasons),
            input_snapshot=dict(input_snapshot),
            recommended_amount=recommended_amount,
            max_eligible_amount=max_eligible_amount,
        )

    @staticmethod
    def _matches(
        rule: PolicyRule,
        input_snapshot: dict[str, Any],
    ) -> bool:
        condition = rule.condition

        if not condition:
            return True

        for field, expected in condition.items():
            if input_snapshot.get(field) != expected:
                return False

        return True

    @staticmethod
    def _route_for_effect(
        effect: PolicyRuleEffect,
        *,
        current_route: DecisionRoute,
    ) -> DecisionRoute:
        if effect == PolicyRuleEffect.REQUIRE_MANUAL_REVIEW:
            return DecisionRoute.MANUAL_REVIEW

        if effect == PolicyRuleEffect.REQUIRE_ADDITIONAL_INFORMATION:
            return DecisionRoute.PENDING_ADDITIONAL_INFORMATION

        if effect == PolicyRuleEffect.REQUIRE_EXTERNAL_PROVIDER:
            return DecisionRoute.PENDING_EXTERNAL_PROVIDER

        if effect == PolicyRuleEffect.REJECT:
            return DecisionRoute.AUTO_REJECTED

        # ALLOW never creates automatic approval in the active lending flow.
        if effect == PolicyRuleEffect.ALLOW:
            return current_route

        return DecisionRoute.ERROR_REQUIRES_REVIEW

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        if value is None:
            return None

        if isinstance(value, Decimal):
            return value

        return Decimal(str(value))