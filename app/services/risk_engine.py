from dataclasses import dataclass
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


@dataclass(frozen=True)
class RiskScorecardResult:
    score: Decimal
    factors: tuple[RiskFactor, ...]
    flags: tuple[RiskFlag, ...]


class RiskScorecardV1:
    """
    Deterministic and explainable initial risk scorecard.

    This component measures risk only.

    It does NOT:
    - approve or reject loans
    - determine pricing
    - determine loan limits
    - determine eligibility

    Those responsibilities belong to the Policy Engine.
    """

    VERSION = "risk-scorecard-v1"
    MAX_SCORE = Decimal("100")

    def evaluate(self, data: RiskEngineInput) -> RiskScorecardResult:
        score = Decimal("0")
        factors: list[RiskFactor] = []
        flags: list[RiskFlag] = []

        score, credit_factors, credit_flags = self._credit_score_rule(
            score,
            data.credit_score,
        )
        factors.extend(credit_factors)
        flags.extend(credit_flags)

        score, delinquency_factors, delinquency_flags = (
            self._delinquency_rule(
                score,
                data.delinquent_accounts,
            )
        )
        factors.extend(delinquency_factors)
        flags.extend(delinquency_flags)

        score, inquiry_factors, inquiry_flags = self._inquiry_rule(
            score,
            data.recent_inquiries,
        )
        factors.extend(inquiry_factors)
        flags.extend(inquiry_flags)

        score, fraud_factors, fraud_flags = self._fraud_rule(
            score,
            data.fraud_risk_level,
        )
        factors.extend(fraud_factors)
        flags.extend(fraud_flags)

        score, obligation_factors, obligation_flags = (
            self._obligation_ratio_rule(
                score,
                data.existing_obligation_ratio,
            )
        )
        factors.extend(obligation_factors)
        flags.extend(obligation_flags)

        score, disposable_factors, disposable_flags = (
            self._disposable_income_rule(
                score,
                data.disposable_monthly_income,
            )
        )
        factors.extend(disposable_factors)
        flags.extend(disposable_flags)

        return RiskScorecardResult(
            score=min(score, self.MAX_SCORE),
            factors=tuple(factors),
            flags=tuple(flags),
        )

    @staticmethod
    def _credit_score_rule(
        score: Decimal,
        credit_score: int | None,
    ) -> tuple[
        Decimal,
        list[RiskFactor],
        list[RiskFlag],
    ]:
        if credit_score is None:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="CREDIT_SCORE_MISSING",
                        description="Credit score is unavailable.",
                        severity="MEDIUM",
                    )
                ],
            )

        if credit_score < 600:
            contribution = Decimal("25")
            impact = "HIGH"
        elif credit_score < 650:
            contribution = Decimal("18")
            impact = "MEDIUM"
        elif credit_score < 700:
            contribution = Decimal("10")
            impact = "LOW"
        else:
            contribution = Decimal("0")
            impact = "LOW"

        factor = RiskFactor(
            code="CREDIT_SCORE",
            description="Credit score contributed to the risk assessment.",
            category="CREDIT",
            impact=impact,
            value=str(credit_score),
        )

        return score + contribution, [factor], []

    @staticmethod
    def _delinquency_rule(
        score: Decimal,
        delinquent_accounts: int | None,
    ) -> tuple[
        Decimal,
        list[RiskFactor],
        list[RiskFlag],
    ]:
        if delinquent_accounts is None:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="DELINQUENCY_DATA_MISSING",
                        description="Delinquent account information is unavailable.",
                        severity="MEDIUM",
                    )
                ],
            )

        if delinquent_accounts < 0:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="DELINQUENCY_DATA_INVALID",
                        description="Delinquent account count cannot be negative.",
                        severity="HIGH",
                    )
                ],
            )

        if delinquent_accounts == 0:
            contribution = Decimal("0")
            impact = "LOW"
        elif delinquent_accounts == 1:
            contribution = Decimal("15")
            impact = "MEDIUM"
        else:
            contribution = Decimal("25")
            impact = "HIGH"

        factor = RiskFactor(
            code="DELINQUENT_ACCOUNTS",
            description="Delinquent accounts contributed to the risk assessment.",
            category="CREDIT",
            impact=impact,
            value=str(delinquent_accounts),
        )

        return score + contribution, [factor], []

    @staticmethod
    def _inquiry_rule(
        score: Decimal,
        recent_inquiries: int | None,
    ) -> tuple[
        Decimal,
        list[RiskFactor],
        list[RiskFlag],
    ]:
        if recent_inquiries is None:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="RECENT_INQUIRIES_MISSING",
                        description="Recent credit inquiry information is unavailable.",
                        severity="LOW",
                    )
                ],
            )

        if recent_inquiries < 0:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="RECENT_INQUIRIES_INVALID",
                        description="Recent inquiry count cannot be negative.",
                        severity="MEDIUM",
                    )
                ],
            )

        if recent_inquiries <= 1:
            contribution = Decimal("0")
            impact = "LOW"
        elif recent_inquiries <= 3:
            contribution = Decimal("5")
            impact = "LOW"
        else:
            contribution = Decimal("10")
            impact = "MEDIUM"

        factor = RiskFactor(
            code="RECENT_INQUIRIES",
            description="Recent credit inquiries contributed to the risk assessment.",
            category="CREDIT",
            impact=impact,
            value=str(recent_inquiries),
        )

        return score + contribution, [factor], []

    @staticmethod
    def _fraud_rule(
        score: Decimal,
        fraud_risk_level: str | None,
    ) -> tuple[
        Decimal,
        list[RiskFactor],
        list[RiskFlag],
    ]:
        if fraud_risk_level is None:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="FRAUD_RISK_MISSING",
                        description="Fraud risk assessment is unavailable.",
                        severity="HIGH",
                    )
                ],
            )

        normalized = fraud_risk_level.upper()

        contributions = {
            "LOW": (Decimal("0"), "LOW"),
            "MEDIUM": (Decimal("20"), "MEDIUM"),
            "HIGH": (Decimal("35"), "HIGH"),
            "UNKNOWN": (Decimal("10"), "MEDIUM"),
        }

        if normalized not in contributions:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="FRAUD_RISK_INVALID",
                        description="Fraud risk level is not recognized.",
                        severity="HIGH",
                    )
                ],
            )

        contribution, impact = contributions[normalized]

        factor = RiskFactor(
            code="FRAUD_RISK",
            description="Fraud assessment contributed to the risk assessment.",
            category="FRAUD",
            impact=impact,
            value=normalized,
        )

        return score + contribution, [factor], []

    @staticmethod
    def _obligation_ratio_rule(
        score: Decimal,
        obligation_ratio: Decimal | None,
    ) -> tuple[
        Decimal,
        list[RiskFactor],
        list[RiskFlag],
    ]:
        if obligation_ratio is None:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="OBLIGATION_RATIO_MISSING",
                        description="Existing obligation ratio is unavailable.",
                        severity="MEDIUM",
                    )
                ],
            )

        if obligation_ratio < Decimal("0"):
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="OBLIGATION_RATIO_INVALID",
                        description="Existing obligation ratio cannot be negative.",
                        severity="HIGH",
                    )
                ],
            )

        if obligation_ratio <= Decimal("0.20"):
            contribution = Decimal("0")
            impact = "LOW"
        elif obligation_ratio <= Decimal("0.40"):
            contribution = Decimal("10")
            impact = "LOW"
        elif obligation_ratio <= Decimal("0.60"):
            contribution = Decimal("20")
            impact = "MEDIUM"
        else:
            contribution = Decimal("30")
            impact = "HIGH"

        factor = RiskFactor(
            code="EXISTING_OBLIGATION_RATIO",
            description="Existing obligations contributed to the risk assessment.",
            category="AFFORDABILITY",
            impact=impact,
            value=str(obligation_ratio),
        )

        return score + contribution, [factor], []

    @staticmethod
    def _disposable_income_rule(
        score: Decimal,
        disposable_income: Decimal | None,
    ) -> tuple[
        Decimal,
        list[RiskFactor],
        list[RiskFlag],
    ]:
        if disposable_income is None:
            return (
                score,
                [],
                [
                    RiskFlag(
                        code="DISPOSABLE_INCOME_MISSING",
                        description="Disposable monthly income is unavailable.",
                        severity="MEDIUM",
                    )
                ],
            )

        if disposable_income < Decimal("0"):
            contribution = Decimal("20")
            impact = "HIGH"
        elif disposable_income == Decimal("0"):
            contribution = Decimal("15")
            impact = "HIGH"
        else:
            contribution = Decimal("0")
            impact = "LOW"

        factor = RiskFactor(
            code="DISPOSABLE_MONTHLY_INCOME",
            description="Disposable monthly income contributed to the risk assessment.",
            category="AFFORDABILITY",
            impact=impact,
            value=str(disposable_income),
        )

        return score + contribution, [factor], []


class RiskEngine:
    def __init__(self, scorecard: RiskScorecardV1 | None = None):
        self.scorecard = scorecard or RiskScorecardV1()

    @staticmethod
    def _derive_band(score: Decimal) -> RiskBand:
        if score < Decimal("30"):
            return RiskBand.LOW

        if score < Decimal("60"):
            return RiskBand.MEDIUM

        return RiskBand.HIGH

    @staticmethod
    def _derive_action(
        band: RiskBand,
        flags: tuple[RiskFlag, ...],
    ) -> RiskAction:
        high_severity_flags = any(
            flag.severity == "HIGH"
            for flag in flags
        )

        if high_severity_flags:
            return RiskAction.MANUAL_REVIEW

        if band == RiskBand.HIGH:
            return RiskAction.MANUAL_REVIEW

        return RiskAction.ASSESS

    def assess(self, data: RiskEngineInput) -> RiskEngineResult:
        result = self.scorecard.evaluate(data)

        risk_band = self._derive_band(result.score)
        recommended_action = self._derive_action(
            risk_band,
            result.flags,
        )

        return RiskEngineResult(
            model_version=self.scorecard.VERSION,
            status=RiskAssessmentStatus.COMPLETED,
            risk_score=result.score,
            risk_band=risk_band,
            factors=result.factors,
            flags=result.flags,
            recommended_action=recommended_action,
            recommended_amount=None,
            max_eligible_amount=None,
            failure_reason=None,
        )