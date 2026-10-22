from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


class DisbursementStatus(StrEnum):
    PENDING = "PENDING"  # recorded, not yet sent to the provider
    PROCESSING = "PROCESSING"  # claimed / sent; outcome not final
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"  # provider definitively did not pay
    REVERSED = "REVERSED"  # paid, then returned
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # state is uncertain/contradictory


S = DisbursementStatus

TRANSITIONS: dict[DisbursementStatus, frozenset[DisbursementStatus]] = {
    S.PENDING: frozenset({S.PROCESSING, S.FAILED, S.REQUIRES_REVIEW}),
    S.PROCESSING: frozenset({S.SUCCESS, S.FAILED, S.REQUIRES_REVIEW}),
    S.SUCCESS: frozenset({S.REVERSED}),
    # A "success" arriving after a failure means money may have moved: a human
    # must look, it is never trusted automatically.
    S.FAILED: frozenset({S.REQUIRES_REVIEW}),
    # Leaves review only through a provider-confirmed recheck.
    S.REQUIRES_REVIEW: frozenset({S.SUCCESS, S.FAILED}),
    S.REVERSED: frozenset(),
}

# At most one of these per offer: money is, or may be, on its way or paid.
LIVE_STATUSES = frozenset({S.PENDING, S.PROCESSING, S.SUCCESS, S.REQUIRES_REVIEW})

# Statuses a provider may report (NOT_FOUND only from a status lookup).
PROVIDER_STATUSES = frozenset({"PROCESSING", "SUCCESS", "FAILED", "REVERSED"})

# Customers never see internal uncertainty.
CUSTOMER_STATUS = {
    S.PENDING: "PROCESSING",
    S.PROCESSING: "PROCESSING",
    S.REQUIRES_REVIEW: "PROCESSING",
    S.SUCCESS: "DISBURSED",
    S.FAILED: "FAILED",
    S.REVERSED: "REVERSED",
}

FAILURE_CODES = frozenset(
    {
        "PROVIDER_REJECTED",
        "INVALID_BENEFICIARY",
        "INSUFFICIENT_FUNDS",
        "BANK_DECLINED",
        "PROVIDER_FAILED",
        "PROVIDER_NOT_FOUND",
    }
)


def utcnow() -> datetime:
    """Single clock for this module (tests fast-forward it)."""
    return datetime.now(UTC)


def can_transition(current: DisbursementStatus, new: DisbursementStatus) -> bool:
    return new in TRANSITIONS[current]


class DisbursementError(ValueError):
    pass


class DisbursementNotFound(DisbursementError):
    pass


class DisbursementConflict(DisbursementError):
    pass


class DisbursementUnavailable(DisbursementError):
    """Provider unreachable and the outcome is unknown."""
