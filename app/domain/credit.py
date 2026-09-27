from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class CreditAssessmentStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CreditScoreType(StrEnum):
    BUREAU = "BUREAU"


@dataclass(frozen=True)
class CreditReport:
    provider: str
    provider_reference: str

    score: int | None
    score_type: CreditScoreType

    total_accounts: int | None = None
    active_accounts: int | None = None
    delinquent_accounts: int | None = None
    total_outstanding: Decimal | None = None
    recent_inquiries: int | None = None

    report_received_at: datetime | None = None


@dataclass(frozen=True)
class CreditAssessmentResult:
    provider: str
    provider_reference: str
    status: CreditAssessmentStatus

    report: CreditReport | None = None
    failure_reason: str | None = None