from decimal import Decimal

from app.domain.risk import (
    RiskAction,
    RiskAssessmentStatus,
    RiskBand,
    RiskEngineInput,
    RiskEngineResult,
    RiskFactor,
    RiskFlag,
)


def test_risk_engine_input():
    result = RiskEngineInput(
        credit_score=720,
        delinquent_accounts=0,
        recent_inquiries=1,
        fraud_risk_level="LOW",
        monthly_income=Decimal("30000.00"),
        monthly_obligations=Decimal("5000.00"),
        disposable_monthly_income=Decimal("25000.00"),
        existing_obligation_ratio=Decimal("0.1667"),
        requested_amount=Decimal("15000.00"),
        requested_tenure_days=30,
    )

    assert result.credit_score == 720
    assert result.fraud_risk_level == "LOW"
    assert result.requested_amount == Decimal("15000.00")


def test_risk_factor():
    factor = RiskFactor(
        code="CREDIT_SCORE",
        description="Credit score available",
        category="CREDIT",
        impact="POSITIVE",
        value="720",
    )

    assert factor.code == "CREDIT_SCORE"
    assert factor.category == "CREDIT"
    assert factor.impact == "POSITIVE"


def test_risk_flag():
    flag = RiskFlag(
        code="RECENT_DELINQUENCY",
        description="Recent delinquency detected",
        severity="HIGH",
    )

    assert flag.code == "RECENT_DELINQUENCY"
    assert flag.severity == "HIGH"


def test_risk_engine_result():
    result = RiskEngineResult(
        model_version="v1",
        status=RiskAssessmentStatus.COMPLETED,
        risk_score=Decimal("72.50"),
        risk_band=RiskBand.MEDIUM,
        factors=(
            RiskFactor(
                code="CREDIT_SCORE",
                description="Credit score available",
                category="CREDIT",
                impact="POSITIVE",
                value="720",
            ),
        ),
        flags=(),
        recommended_action=RiskAction.ASSESS,
        recommended_amount=Decimal("10000.00"),
        max_eligible_amount=Decimal("15000.00"),
    )

    assert result.status == RiskAssessmentStatus.COMPLETED
    assert result.risk_score == Decimal("72.50")
    assert result.risk_band == RiskBand.MEDIUM
    assert result.model_version == "v1"
    assert len(result.factors) == 1