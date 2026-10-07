from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.policy import (
    DecisionRoute,
    PolicyRule,
    PolicyRuleEffect,
    PolicyVersion,
)
from app.services.policy_engine import PolicyEngine


def make_policy_version() -> PolicyVersion:
    return PolicyVersion(
        version="policy-v1",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="MANUAL_REVIEW",
                order=10,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                reason_code="MANUAL_REVIEW_REQUIRED",
            ),
        ),
    )


def test_evaluate_routes_to_manual_review():
    engine = PolicyEngine()
    policy = make_policy_version()

    user_id = uuid4()
    application_id = uuid4()
    evaluated_at = datetime(2026, 9, 29, tzinfo=timezone.utc)

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={
            "risk_band": "MEDIUM",
            "recommended_amount": "5000",
            "max_eligible_amount": "9000",
        },
        evaluated_at=evaluated_at,
        user_id=user_id,
        loan_application_id=application_id,
    )

    assert result.policy_version == "policy-v1"
    assert result.decision_route == DecisionRoute.MANUAL_REVIEW
    assert result.matched_rule_codes == ("MANUAL_REVIEW",)
    assert result.reasons == ("MANUAL_REVIEW_REQUIRED",)
    assert result.recommended_amount == Decimal("5000")
    assert result.max_eligible_amount == Decimal("9000")


def test_rules_are_evaluated_in_deterministic_order():
    engine = PolicyEngine()

    policy = PolicyVersion(
        version="policy-v2",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="SECOND",
                order=20,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                condition={"risk_band": "MEDIUM"},
                reason_code="SECOND_REASON",
            ),
            PolicyRule(
                code="FIRST",
                order=10,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                condition={"risk_band": "MEDIUM"},
                reason_code="FIRST_REASON",
            ),
        ),
    )

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={"risk_band": "MEDIUM"},
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        user_id=uuid4(),
        loan_application_id=uuid4(),
    )

    assert result.matched_rule_codes == ("FIRST", "SECOND")
    assert result.reasons == ("FIRST_REASON", "SECOND_REASON")
    assert result.decision_route == DecisionRoute.MANUAL_REVIEW


def test_reject_rule_stops_later_rules():
    engine = PolicyEngine()

    policy = PolicyVersion(
        version="policy-v3",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="REJECT_RISK",
                order=10,
                effect=PolicyRuleEffect.REJECT,
                condition={"risk_band": "HIGH"},
                reason_code="HIGH_RISK",
            ),
            PolicyRule(
                code="MANUAL_REVIEW",
                order=20,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                condition={"risk_band": "HIGH"},
                reason_code="MANUAL_REVIEW_REQUIRED",
            ),
        ),
    )

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={"risk_band": "HIGH"},
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        user_id=uuid4(),
        loan_application_id=uuid4(),
    )

    assert result.decision_route == DecisionRoute.AUTO_REJECTED
    assert result.matched_rule_codes == ("REJECT_RISK",)
    assert result.reasons == ("HIGH_RISK",)


@pytest.mark.parametrize(
    ("effect", "expected_route"),
    [
        (
            PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
            DecisionRoute.MANUAL_REVIEW,
        ),
        (
            PolicyRuleEffect.REQUIRE_ADDITIONAL_INFORMATION,
            DecisionRoute.PENDING_ADDITIONAL_INFORMATION,
        ),
        (
            PolicyRuleEffect.REQUIRE_EXTERNAL_PROVIDER,
            DecisionRoute.PENDING_EXTERNAL_PROVIDER,
        ),
        (
            PolicyRuleEffect.REJECT,
            DecisionRoute.AUTO_REJECTED,
        ),
    ],
)
def test_rule_effect_maps_to_decision_route(effect, expected_route):
    engine = PolicyEngine()

    policy = PolicyVersion(
        version="policy-route-test",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="ROUTE_TEST",
                order=10,
                effect=effect,
                reason_code="ROUTE_REASON",
            ),
        ),
    )

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={"value": "test"},
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        user_id=uuid4(),
        loan_application_id=uuid4(),
    )

    assert result.decision_route == expected_route


def test_allow_does_not_auto_approve():
    engine = PolicyEngine()

    policy = PolicyVersion(
        version="policy-allow",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="ALLOW",
                order=10,
                effect=PolicyRuleEffect.ALLOW,
                reason_code="POLICY_ALLOWED",
            ),
        ),
    )

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={"value": "test"},
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        user_id=uuid4(),
        loan_application_id=uuid4(),
    )

    assert result.decision_route == DecisionRoute.MANUAL_REVIEW


def test_same_inputs_produce_reproducible_result():
    engine = PolicyEngine()

    policy = make_policy_version()

    user_id = uuid4()
    application_id = uuid4()
    evaluated_at = datetime(2026, 9, 29, tzinfo=timezone.utc)

    snapshot = {
        "risk_band": "MEDIUM",
        "recommended_amount": "5000",
        "max_eligible_amount": "9000",
    }

    first = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot=snapshot,
        evaluated_at=evaluated_at,
        user_id=user_id,
        loan_application_id=application_id,
    )

    second = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot=snapshot,
        evaluated_at=evaluated_at,
        user_id=user_id,
        loan_application_id=application_id,
    )

    assert first.policy_version == second.policy_version
    assert first.decision_route == second.decision_route
    assert first.matched_rule_codes == second.matched_rule_codes
    assert first.reasons == second.reasons
    assert first.input_snapshot == second.input_snapshot
    assert first.recommended_amount == second.recommended_amount
    assert first.max_eligible_amount == second.max_eligible_amount


def test_empty_rules_are_rejected():
    engine = PolicyEngine()

    policy = make_policy_version()

    with pytest.raises(ValueError, match="at least one policy rule"):
        engine.evaluate(
            policy_version=policy,
            rules=(),
            input_snapshot={"risk_band": "LOW"},
            evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
            user_id=uuid4(),
            loan_application_id=uuid4(),
        )


def test_empty_input_snapshot_is_rejected():
    engine = PolicyEngine()

    policy = make_policy_version()

    with pytest.raises(ValueError, match="input_snapshot is required"):
        engine.evaluate(
            policy_version=policy,
            rules=policy.rules,
            input_snapshot={},
            evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
            user_id=uuid4(),
            loan_application_id=uuid4(),
        )

def test_policy_rule_can_constrain_loan_level():
    engine = PolicyEngine()

    policy = PolicyVersion(
        version="policy-loan-level-v1",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="LEVEL_1_MANUAL_REVIEW",
                order=10,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                condition={"loan_level_code": "LEVEL_1"},
                reason_code="LEVEL_1_MANUAL_REVIEW",
            ),
        ),
    )

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={
            "loan_level_code": "LEVEL_1",
            "risk_band": "MEDIUM",
        },
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        user_id=uuid4(),
        loan_application_id=uuid4(),
    )

    assert result.decision_route == DecisionRoute.MANUAL_REVIEW
    assert result.matched_rule_codes == (
        "LEVEL_1_MANUAL_REVIEW",
    )
    assert result.reasons == (
        "LEVEL_1_MANUAL_REVIEW",
    )


def test_policy_rule_for_different_loan_level_does_not_match():
    engine = PolicyEngine()

    policy = PolicyVersion(
        version="policy-loan-level-v2",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rules=(
            PolicyRule(
                code="LEVEL_1_MANUAL_REVIEW",
                order=10,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                condition={"loan_level_code": "LEVEL_1"},
                reason_code="LEVEL_1_MANUAL_REVIEW",
            ),
            PolicyRule(
                code="DEFAULT_MANUAL_REVIEW",
                order=20,
                effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
                reason_code="DEFAULT_MANUAL_REVIEW",
            ),
        ),
    )

    result = engine.evaluate(
        policy_version=policy,
        rules=policy.rules,
        input_snapshot={
            "loan_level_code": "LEVEL_2",
        },
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        user_id=uuid4(),
        loan_application_id=uuid4(),
    )

    assert result.matched_rule_codes == (
        "DEFAULT_MANUAL_REVIEW",
    )
    assert result.reasons == (
        "DEFAULT_MANUAL_REVIEW",
    )
    assert result.decision_route == DecisionRoute.MANUAL_REVIEW