from app.domain.decision import (
    DecisionReasonCode,
    DecisionRoute,
)
from app.services.decision_router import DecisionRouter


def test_manual_review_route_is_preserved():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.MANUAL_REVIEW,
    )

    assert result.route == DecisionRoute.MANUAL_REVIEW
    assert result.reason_codes == (
        DecisionReasonCode.MANUAL_REVIEW_REQUIRED.value,
    )


def test_auto_approved_is_converted_to_manual_review():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.AUTO_APPROVED,
        input_snapshot={"risk_band": "LOW"},
    )

    assert result.route == DecisionRoute.MANUAL_REVIEW
    assert DecisionReasonCode.MANUAL_REVIEW_REQUIRED.value in result.reason_codes
    assert result.input_snapshot == {"risk_band": "LOW"}


def test_auto_rejected_route_is_preserved():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.AUTO_REJECTED,
    )

    assert result.route == DecisionRoute.AUTO_REJECTED
    assert result.reason_codes == (
        DecisionReasonCode.POLICY_REJECTED.value,
    )


def test_additional_information_route_is_preserved():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.PENDING_ADDITIONAL_INFORMATION,
    )

    assert result.route == DecisionRoute.PENDING_ADDITIONAL_INFORMATION
    assert result.reason_codes == (
        DecisionReasonCode.ADDITIONAL_INFORMATION_REQUIRED.value,
    )


def test_external_provider_route_is_preserved():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.PENDING_EXTERNAL_PROVIDER,
    )

    assert result.route == DecisionRoute.PENDING_EXTERNAL_PROVIDER
    assert result.reason_codes == (
        DecisionReasonCode.EXTERNAL_PROVIDER_REQUIRED.value,
    )


def test_error_route_is_preserved():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.ERROR_REQUIRES_REVIEW,
    )

    assert result.route == DecisionRoute.ERROR_REQUIRES_REVIEW
    assert result.reason_codes == (
        DecisionReasonCode.ASSESSMENT_ERROR.value,
    )


def test_explicit_reasons_are_preserved():
    router = DecisionRouter()

    result = router.route(
        policy_route=DecisionRoute.MANUAL_REVIEW,
        reason_codes=("CUSTOM_REASON",),
        reasons=("Custom review reason.",),
    )

    assert result.reason_codes == ("CUSTOM_REASON",)
    assert result.reasons == ("Custom review reason.",)
