import pytest

from app.domain.decision import (
    DecisionReasonCode,
    DecisionResult,
    DecisionRoute,
)


def test_all_supported_decision_routes_exist():
    assert DecisionRoute.MANUAL_REVIEW.value == "MANUAL_REVIEW"
    assert DecisionRoute.AUTO_APPROVED.value == "AUTO_APPROVED"
    assert DecisionRoute.AUTO_REJECTED.value == "AUTO_REJECTED"
    assert (
        DecisionRoute.PENDING_ADDITIONAL_INFORMATION.value
        == "PENDING_ADDITIONAL_INFORMATION"
    )
    assert (
        DecisionRoute.PENDING_EXTERNAL_PROVIDER.value
        == "PENDING_EXTERNAL_PROVIDER"
    )
    assert (
        DecisionRoute.ERROR_REQUIRES_REVIEW.value
        == "ERROR_REQUIRES_REVIEW"
    )


def test_decision_result_requires_explanation():
    with pytest.raises(
        ValueError,
        match="must retain an explanation",
    ):
        DecisionResult(
            route=DecisionRoute.MANUAL_REVIEW,
        )


def test_manual_review_decision_is_valid():
    result = DecisionResult(
        route=DecisionRoute.MANUAL_REVIEW,
        reason_codes=(
            DecisionReasonCode.MANUAL_REVIEW_REQUIRED.value,
        ),
        reasons=("Lender review is required.",),
    )

    assert result.route == DecisionRoute.MANUAL_REVIEW
    assert result.reason_codes == ("MANUAL_REVIEW_REQUIRED",)


def test_decision_result_preserves_input_snapshot():
    result = DecisionResult(
        route=DecisionRoute.PENDING_EXTERNAL_PROVIDER,
        reason_codes=(
            DecisionReasonCode.EXTERNAL_PROVIDER_REQUIRED.value,
        ),
        input_snapshot={
            "credit_status": "PENDING",
            "provider": "credit-bureau",
        },
    )

    assert result.input_snapshot["credit_status"] == "PENDING"
    assert result.input_snapshot["provider"] == "credit-bureau"


def test_auto_approval_is_not_permitted_in_active_flow():
    with pytest.raises(
        ValueError,
        match="AUTO_APPROVED is not permitted",
    ):
        DecisionResult(
            route=DecisionRoute.AUTO_APPROVED,
            reason_codes=("SYSTEM_ROUTE",),
        )
