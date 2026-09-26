from decimal import Decimal

from app.domain.risk import (
    RiskAction,
    RiskAssessmentStatus,
    RiskBand,
    RiskEngineInput,
)
from app.services.risk_engine import RiskEngine, RiskScorecardV1


def test_scorecard_has_stable_version():
    assert RiskScorecardV1.VERSION == "risk-scorecard-v1"


def test_low_risk_inputs_produce_low_risk_band():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=750,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level="LOW",
            monthly_income=Decimal("30000"),
            monthly_obligations=Decimal("3000"),
            disposable_monthly_income=Decimal("27000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    assert result.status == RiskAssessmentStatus.COMPLETED
    assert result.risk_score == Decimal("0")
    assert result.risk_band == RiskBand.LOW
    assert result.recommended_action == RiskAction.ASSESS


def test_lower_credit_score_increases_risk():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=590,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level="LOW",
            disposable_monthly_income=Decimal("20000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    assert result.risk_score == Decimal("25")
    assert result.risk_band == RiskBand.LOW

    codes = {factor.code for factor in result.factors}
    assert "CREDIT_SCORE" in codes


def test_multiple_delinquencies_increase_risk():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=700,
            delinquent_accounts=2,
            recent_inquiries=0,
            fraud_risk_level="LOW",
            disposable_monthly_income=Decimal("20000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    assert result.risk_score == Decimal("25")
    assert result.risk_band == RiskBand.LOW


def test_high_fraud_risk_adds_significant_risk():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=700,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level="HIGH",
            disposable_monthly_income=Decimal("20000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    assert result.risk_score == Decimal("35")
    assert result.risk_band == RiskBand.MEDIUM


def test_high_obligation_ratio_increases_risk():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=700,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level="LOW",
            disposable_monthly_income=Decimal("20000"),
            existing_obligation_ratio=Decimal("0.70"),
        )
    )

    assert result.risk_score == Decimal("30")
    assert result.risk_band == RiskBand.MEDIUM


def test_negative_disposable_income_adds_risk():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=700,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level="LOW",
            disposable_monthly_income=Decimal("-1000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    assert result.risk_score == Decimal("20")
    assert result.risk_band == RiskBand.LOW


def test_combined_risk_can_require_manual_review():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=580,
            delinquent_accounts=3,
            recent_inquiries=5,
            fraud_risk_level="HIGH",
            disposable_monthly_income=Decimal("-1000"),
            existing_obligation_ratio=Decimal("0.70"),
        )
    )

    assert result.risk_score == Decimal("100")
    assert result.risk_band == RiskBand.HIGH
    assert result.recommended_action == RiskAction.MANUAL_REVIEW


def test_missing_inputs_create_explicit_flags():
    engine = RiskEngine()

    result = engine.assess(RiskEngineInput())

    codes = {flag.code for flag in result.flags}

    assert "CREDIT_SCORE_MISSING" in codes
    assert "DELINQUENCY_DATA_MISSING" in codes
    assert "RECENT_INQUIRIES_MISSING" in codes
    assert "FRAUD_RISK_MISSING" in codes
    assert "OBLIGATION_RATIO_MISSING" in codes
    assert "DISPOSABLE_INCOME_MISSING" in codes


def test_missing_critical_fraud_data_requires_manual_review():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=750,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level=None,
            disposable_monthly_income=Decimal("20000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    assert result.risk_score == Decimal("0")
    assert result.risk_band == RiskBand.LOW
    assert result.recommended_action == RiskAction.MANUAL_REVIEW


def test_invalid_fraud_risk_creates_high_severity_flag():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=750,
            delinquent_accounts=0,
            recent_inquiries=0,
            fraud_risk_level="INVALID",
            disposable_monthly_income=Decimal("20000"),
            existing_obligation_ratio=Decimal("0.10"),
        )
    )

    codes = {flag.code for flag in result.flags}

    assert "FRAUD_RISK_INVALID" in codes
    assert result.recommended_action == RiskAction.MANUAL_REVIEW


def test_score_is_capped_at_100():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=500,
            delinquent_accounts=10,
            recent_inquiries=10,
            fraud_risk_level="HIGH",
            disposable_monthly_income=Decimal("-10000"),
            existing_obligation_ratio=Decimal("2.00"),
        )
    )

    assert result.risk_score == Decimal("100")
    assert result.risk_band == RiskBand.HIGH


def test_result_is_explainable():
    engine = RiskEngine()

    result = engine.assess(
        RiskEngineInput(
            credit_score=590,
            delinquent_accounts=2,
            recent_inquiries=4,
            fraud_risk_level="HIGH",
            disposable_monthly_income=Decimal("-1000"),
            existing_obligation_ratio=Decimal("0.70"),
        )
    )

    factor_codes = {factor.code for factor in result.factors}

    assert "CREDIT_SCORE" in factor_codes
    assert "DELINQUENT_ACCOUNTS" in factor_codes
    assert "RECENT_INQUIRIES" in factor_codes
    assert "FRAUD_RISK" in factor_codes
    assert "EXISTING_OBLIGATION_RATIO" in factor_codes
    assert "DISPOSABLE_MONTHLY_INCOME" in factor_codes