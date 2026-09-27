from dataclasses import dataclass
from enum import StrEnum


class FraudAssessmentStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FraudRiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FraudSignal:
    code: str
    description: str
    severity: str


@dataclass(frozen=True)
class FraudAssessmentResult:
    provider: str
    provider_reference: str
    status: FraudAssessmentStatus
    risk_level: FraudRiskLevel = FraudRiskLevel.UNKNOWN
    signals: tuple[FraudSignal, ...] = ()
    failure_reason: str | None = None