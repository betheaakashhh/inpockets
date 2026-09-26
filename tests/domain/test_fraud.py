from app.domain.fraud import (
    FraudAssessmentResult,
    FraudAssessmentStatus,
    FraudRiskLevel,
    FraudSignal,
)


def test_fraud_assessment_result_defaults():
    result = FraudAssessmentResult(
        provider="development",
        provider_reference="fraud-test-001",
        status=FraudAssessmentStatus.COMPLETED,
    )

    assert result.status == FraudAssessmentStatus.COMPLETED
    assert result.risk_level == FraudRiskLevel.UNKNOWN
    assert result.signals == ()
    assert result.failure_reason is None


def test_fraud_assessment_result_with_signals():
    signal = FraudSignal(
        code="DEVICE_VELOCITY",
        description="Multiple applications from the same device",
        severity="MEDIUM",
    )

    result = FraudAssessmentResult(
        provider="development",
        provider_reference="fraud-test-002",
        status=FraudAssessmentStatus.COMPLETED,
        risk_level=FraudRiskLevel.MEDIUM,
        signals=(signal,),
    )

    assert result.risk_level == FraudRiskLevel.MEDIUM
    assert len(result.signals) == 1
    assert result.signals[0].code == "DEVICE_VELOCITY"
    assert result.signals[0].severity == "MEDIUM"


def test_fraud_assessment_failure():
    result = FraudAssessmentResult(
        provider="development",
        provider_reference="fraud-test-003",
        status=FraudAssessmentStatus.FAILED,
        failure_reason="Provider unavailable",
    )

    assert result.status == FraudAssessmentStatus.FAILED
    assert result.failure_reason == "Provider unavailable"