from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class AssessmentSignal:
    """A normalized signal supplied to one or more assessment components."""

    code: str
    category: str
    value: str | None = None
    source: str | None = None
    reference: str | None = None


@dataclass(frozen=True)
class AssessmentContext:
    """Shared, versioned context for a loan assessment run.

    The context is an in-memory domain contract. Assessment results remain
    persisted in their respective assessment tables.
    """

    user_id: UUID
    loan_application_id: UUID
    requested_amount: Decimal
    requested_tenure_days: int

    context_version: str = "assessment-context-v1"
    assessment_reference: str | None = None
    requested_at: datetime | None = None

    identity_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)
    fraud_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)
    credit_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)
    affordability_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)
    obligation_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)
    customer_history_signals: tuple[AssessmentSignal, ...] = field(
        default_factory=tuple
    )
    application_behavior_signals: tuple[AssessmentSignal, ...] = field(
        default_factory=tuple
    )
    device_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)
    additional_signals: tuple[AssessmentSignal, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.user_id is None:
            raise ValueError("user_id is required")
        if self.loan_application_id is None:
            raise ValueError("loan_application_id is required")
        if self.requested_amount <= Decimal("0"):
            raise ValueError("requested_amount must be greater than zero")
        if self.requested_tenure_days <= 0:
            raise ValueError("requested_tenure_days must be greater than zero")
