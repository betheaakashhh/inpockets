from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class RiskAssessmentStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class RiskBand(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class RiskAction(StrEnum):
    ASSESS = "ASSESS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REFER = "REFER"
    DECLINE = "DECLINE"


@dataclass(frozen=True)
class RiskFactor:
    code: str
    description: str
    category: str
    impact: str
    value: str | None = None


@dataclass(frozen=True)
class RiskFlag:
    code: str
    description: str
    severity: str


@dataclass(frozen=True)
class RiskEngineInput:
    credit_score: int | None = None
    delinquent_accounts: int | None = None
    recent_inquiries: int | None = None

    fraud_risk_level: str | None = None

    monthly_income: Decimal | None = None
    monthly_obligations: Decimal | None = None
    disposable_monthly_income: Decimal | None = None
    existing_obligation_ratio: Decimal | None = None

    requested_amount: Decimal | None = None
    requested_tenure_days: int | None = None


@dataclass(frozen=True)
class RiskEngineResult:
    model_version: str
    status: RiskAssessmentStatus
    risk_score: Decimal | None = None
    risk_band: RiskBand = RiskBand.UNKNOWN
    factors: tuple[RiskFactor, ...] = ()
    flags: tuple[RiskFlag, ...] = ()
    recommended_action: RiskAction = RiskAction.ASSESS
    recommended_amount: Decimal | None = None
    max_eligible_amount: Decimal | None = None
    failure_reason: str | None = None