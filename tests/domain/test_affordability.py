from decimal import Decimal

from app.domain.affordability import (
    AffordabilityAssessmentResult,
    AffordabilityAssessmentStatus,
    AffordabilityFactors,
    AffordabilitySourceType,
)


def test_affordability_assessment_result():
    factors = AffordabilityFactors(
        monthly_income=Decimal("30000.00"),
        monthly_obligations=Decimal("8000.00"),
        requested_amount=Decimal("15000.00"),
        requested_tenure_days=30,
        disposable_monthly_income=Decimal("22000.00"),
    )

    result = AffordabilityAssessmentResult(
        source_type=AffordabilitySourceType.CUSTOMER_DECLARED,
        source_reference="test-source",
        status=AffordabilityAssessmentStatus.COMPLETED,
        factors=factors,
    )

    assert result.status == AffordabilityAssessmentStatus.COMPLETED
    assert result.source_type == AffordabilitySourceType.CUSTOMER_DECLARED
    assert result.factors is not None
    assert result.factors.monthly_income == Decimal("30000.00")
    assert result.factors.disposable_monthly_income == Decimal("22000.00")