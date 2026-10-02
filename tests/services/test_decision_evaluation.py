from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.decision_evaluation import DecisionEvaluationService


@pytest.mark.asyncio
async def test_evaluate_persists_routed_policy_decision():
    user_id = uuid4()
    loan_application_id = uuid4()
    policy_evaluation_id = uuid4()
    evaluated_at = datetime.now(timezone.utc)

    policy_evaluation = SimpleNamespace(
        id=policy_evaluation_id,
        policy_version="policy-v1",
        decision_route="MANUAL_REVIEW",
        reasons=["manual underwriting required"],
        input_snapshot={
            "risk_score": 420,
            "requested_amount": "10000",
        },
        evaluated_at=evaluated_at,
        recommended_amount=Decimal("8000.00"),
        max_eligible_amount=Decimal("10000.00"),
    )

    class FakePolicyEvaluationService:
        async def evaluate(self, **kwargs):
            assert kwargs["user_id"] == user_id
            assert kwargs["loan_application_id"] == loan_application_id
            return policy_evaluation

    class FakeDecisionRouter:
        def route(self, **kwargs):
            assert kwargs["policy_route"].value == "MANUAL_REVIEW"
            assert kwargs["input_snapshot"] == policy_evaluation.input_snapshot

            from app.domain.decision import DecisionResult, DecisionRoute

            return DecisionResult(
                route=DecisionRoute.MANUAL_REVIEW,
                reason_codes=("MANUAL_REVIEW_REQUIRED",),
                reasons=("manual underwriting required",),
                input_snapshot=kwargs["input_snapshot"],
            )

    class FakeLoanDecisionRepository:
        async def create(self, **kwargs):
            assert kwargs["loan_application_id"] == loan_application_id
            assert kwargs["user_id"] == user_id
            assert kwargs["policy_evaluation_id"] == policy_evaluation_id
            assert kwargs["policy_version"] == "policy-v1"
            assert kwargs["decision_route"] == "MANUAL_REVIEW"
            assert kwargs["reason_codes"] == [
                "MANUAL_REVIEW_REQUIRED"
            ]
            assert kwargs["recommended_amount"] == Decimal("8000.00")
            assert kwargs["max_eligible_amount"] == Decimal("10000.00")

            return SimpleNamespace(**kwargs)

    service = DecisionEvaluationService(
        policy_evaluation_service=FakePolicyEvaluationService(),
        decision_router=FakeDecisionRouter(),
        loan_decision_repository=FakeLoanDecisionRepository(),
    )

    result = await service.evaluate(
        user_id=user_id,
        loan_application_id=loan_application_id,
        evaluated_at=evaluated_at,
        input_snapshot={
            "risk_score": 420,
            "requested_amount": "10000",
        },
    )

    assert result.decision_route == "MANUAL_REVIEW"
    assert result.policy_version == "policy-v1"


@pytest.mark.asyncio
async def test_auto_approved_policy_route_cannot_become_automatic_decision():
    from app.domain.decision import DecisionResult, DecisionRoute

    user_id = uuid4()
    loan_application_id = uuid4()
    policy_evaluation_id = uuid4()
    evaluated_at = datetime.now(timezone.utc)

    policy_evaluation = SimpleNamespace(
        id=policy_evaluation_id,
        policy_version="policy-v1",
        decision_route="AUTO_APPROVED",
        reasons=["policy conditions satisfied"],
        input_snapshot={"risk_score": 800},
        evaluated_at=evaluated_at,
        recommended_amount=None,
        max_eligible_amount=None,
    )

    class FakePolicyEvaluationService:
        async def evaluate(self, **kwargs):
            return policy_evaluation

    class FakeDecisionRouter:
        def route(self, **kwargs):
            assert kwargs["policy_route"] == DecisionRoute.AUTO_APPROVED

            return DecisionResult(
                route=DecisionRoute.MANUAL_REVIEW,
                reason_codes=("MANUAL_REVIEW_REQUIRED",),
                reasons=(
                    "Lender admin review is required before approval.",
                ),
                input_snapshot=kwargs["input_snapshot"],
            )

    class FakeLoanDecisionRepository:
        async def create(self, **kwargs):
            assert kwargs["decision_route"] == "MANUAL_REVIEW"
            assert kwargs["decision_route"] != "AUTO_APPROVED"

            return SimpleNamespace(**kwargs)

    service = DecisionEvaluationService(
        policy_evaluation_service=FakePolicyEvaluationService(),
        decision_router=FakeDecisionRouter(),
        loan_decision_repository=FakeLoanDecisionRepository(),
    )

    result = await service.evaluate(
        user_id=user_id,
        loan_application_id=loan_application_id,
        evaluated_at=evaluated_at,
        input_snapshot={"risk_score": 800},
    )

    assert result.decision_route == "MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_policy_version_is_preserved_in_persisted_decision():
    policy_evaluation_id = uuid4()
    user_id = uuid4()
    loan_application_id = uuid4()
    evaluated_at = datetime.now(timezone.utc)

    policy_evaluation = SimpleNamespace(
        id=policy_evaluation_id,
        policy_version="policy-v2026-09",
        decision_route="MANUAL_REVIEW",
        reasons=["manual review"],
        input_snapshot={"risk_score": 500},
        evaluated_at=evaluated_at,
        recommended_amount=Decimal("5000"),
        max_eligible_amount=Decimal("7000"),
    )

    class FakePolicyEvaluationService:
        async def evaluate(self, **kwargs):
            return policy_evaluation

    class FakeDecisionRouter:
        def route(self, **kwargs):
            from app.domain.decision import DecisionResult, DecisionRoute

            return DecisionResult(
                route=DecisionRoute.MANUAL_REVIEW,
                reason_codes=("MANUAL_REVIEW_REQUIRED",),
                reasons=kwargs["reasons"],
                input_snapshot=kwargs["input_snapshot"],
            )

    captured = {}

    class FakeLoanDecisionRepository:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(**kwargs)

    service = DecisionEvaluationService(
        policy_evaluation_service=FakePolicyEvaluationService(),
        decision_router=FakeDecisionRouter(),
        loan_decision_repository=FakeLoanDecisionRepository(),
    )

    await service.evaluate(
        user_id=user_id,
        loan_application_id=loan_application_id,
        evaluated_at=evaluated_at,
        input_snapshot={"risk_score": 500},
    )

    assert captured["policy_evaluation_id"] == policy_evaluation_id
    assert captured["policy_version"] == "policy-v2026-09"
    assert captured["input_snapshot"] == {
        "risk_score": 500
    }