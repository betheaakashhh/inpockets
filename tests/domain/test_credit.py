from datetime import datetime, timezone
from decimal import Decimal

from app.domain.credit import (
    CreditAssessmentResult,
    CreditAssessmentStatus,
    CreditReport,
    CreditScoreType,
)


def test_credit_report_can_represent_completed_bureau_assessment():
    report = CreditReport(
        provider="development",
        provider_reference="dev-credit-123",
        score=742,
        score_type=CreditScoreType.BUREAU,
        total_accounts=4,
        active_accounts=2,
        delinquent_accounts=0,
        total_outstanding=Decimal("18000.00"),
        recent_inquiries=1,
        report_received_at=datetime.now(timezone.utc),
    )

    result = CreditAssessmentResult(
        provider="development",
        provider_reference="dev-credit-123",
        status=CreditAssessmentStatus.COMPLETED,
        report=report,
    )

    assert result.status == CreditAssessmentStatus.COMPLETED
    assert result.report is not None
    assert result.report.score == 742
    assert result.report.delinquent_accounts == 0


def test_credit_assessment_can_have_no_bureau_score():
    result = CreditAssessmentResult(
        provider="development",
        provider_reference="dev-credit-456",
        status=CreditAssessmentStatus.COMPLETED,
        report=CreditReport(
            provider="development",
            provider_reference="dev-credit-456",
            score=None,
            score_type=CreditScoreType.BUREAU,
        ),
    )

    assert result.report is not None
    assert result.report.score is None


def test_credit_assessment_can_fail_without_report():
    result = CreditAssessmentResult(
        provider="development",
        provider_reference="dev-credit-789",
        status=CreditAssessmentStatus.FAILED,
        failure_reason="Provider unavailable.",
    )

    assert result.status == CreditAssessmentStatus.FAILED
    assert result.report is None
    assert result.failure_reason == "Provider unavailable."