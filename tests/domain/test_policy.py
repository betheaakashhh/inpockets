from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.policy import (
    DecisionRoute,
    PolicyEvaluation,
    PolicyRule,
    PolicyRuleEffect,
    PolicyVersion,
)


def test_policy_rule_requires_code_and_valid_order():
    with pytest.raises(ValueError):
        PolicyRule(
            code="",
            order=1,
            effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
        )

    with pytest.raises(ValueError):
        PolicyRule(
            code="manual-review",
            order=-1,
            effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
        )


def test_policy_version_is_time_bounded_and_versioned():
    effective_from = datetime.now(timezone.utc)

    rule = PolicyRule(
        code="always-manual-review",
        order=10,
        effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
    )

    policy = PolicyVersion(
        version="lending-policy-v1",
        rules=(rule,),
        effective_from=effective_from,
    )

    assert policy.version == "lending-policy-v1"
    assert policy.rules == (rule,)
    assert policy.effective_to is None


def test_policy_version_rejects_invalid_effective_window():
    effective_from = datetime.now(timezone.utc)

    rule = PolicyRule(
        code="manual-review",
        order=1,
        effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW,
    )

    with pytest.raises(ValueError):
        PolicyVersion(
            version="lending-policy-v1",
            rules=(rule,),
            effective_from=effective_from,
            effective_to=effective_from,
        )


def test_policy_evaluation_retains_exact_policy_version_and_explanation():
    now = datetime.now(timezone.utc)

    evaluation = PolicyEvaluation(
        id=uuid4(),
        user_id=uuid4(),
        loan_application_id=uuid4(),
        policy_version="lending-policy-v7",
        evaluated_at=now,
        decision_route=DecisionRoute.MANUAL_REVIEW,
        matched_rule_codes=("always-manual-review",),
        reasons=("Lender admin review is required.",),
        input_snapshot={
            "requested_amount": "5000.00",
            "risk_band": "MEDIUM",
        },
        recommended_amount=Decimal("5000.00"),
        max_eligible_amount=Decimal("9000.00"),
    )

    assert evaluation.policy_version == "lending-policy-v7"
    assert evaluation.decision_route == DecisionRoute.MANUAL_REVIEW
    assert evaluation.matched_rule_codes == ("always-manual-review",)
    assert evaluation.input_snapshot["risk_band"] == "MEDIUM"


def test_policy_evaluation_requires_explanation():
    with pytest.raises(ValueError):
        PolicyEvaluation(
            id=uuid4(),
            user_id=uuid4(),
            loan_application_id=uuid4(),
            policy_version="lending-policy-v1",
            evaluated_at=datetime.now(timezone.utc),
            decision_route=DecisionRoute.MANUAL_REVIEW,
        )