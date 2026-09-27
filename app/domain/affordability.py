from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class AffordabilityAssessmentStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AffordabilitySourceType(StrEnum):
    CUSTOMER_DECLARED = "CUSTOMER_DECLARED"
    VERIFIED_DATA = "VERIFIED_DATA"
    EXTERNAL_PROVIDER = "EXTERNAL_PROVIDER"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class AffordabilityFactors:
    monthly_income: Decimal | None = None
    monthly_obligations: Decimal | None = None
    requested_amount: Decimal | None = None
    requested_tenure_days: int | None = None

    disposable_monthly_income: Decimal | None = None
    existing_obligation_ratio: Decimal | None = None


@dataclass(frozen=True)
class AffordabilityAssessmentResult:
    source_type: AffordabilitySourceType
    source_reference: str

    status: AffordabilityAssessmentStatus

    factors: AffordabilityFactors | None = None
    failure_reason: str | None = None