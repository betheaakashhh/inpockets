from __future__ import annotations

from enum import StrEnum


class ESignStatus(StrEnum):
    INITIATED = "INITIATED"  # our record exists; provider call not confirmed
    PENDING = "PENDING"  # provider holds a transaction awaiting the signer
    SIGNED = "SIGNED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"  # evidence conflicts; a human must decide


ESIGN_TRANSITIONS: dict[ESignStatus, frozenset[ESignStatus]] = {
    ESignStatus.INITIATED: frozenset(
        {
            ESignStatus.PENDING,
            ESignStatus.FAILED,
            ESignStatus.EXPIRED,
            ESignStatus.MANUAL_REVIEW,
        }
    ),
    ESignStatus.PENDING: frozenset(
        {
            ESignStatus.SIGNED,
            ESignStatus.FAILED,
            ESignStatus.EXPIRED,
            ESignStatus.MANUAL_REVIEW,
        }
    ),
    # A late "signed" for an expired/failed transaction is never trusted
    # automatically; it goes to a human.
    ESignStatus.EXPIRED: frozenset({ESignStatus.MANUAL_REVIEW}),
    ESignStatus.FAILED: frozenset({ESignStatus.MANUAL_REVIEW}),
    ESignStatus.MANUAL_REVIEW: frozenset(),  # resolved by an admin workflow
    ESignStatus.SIGNED: frozenset(),  # final
}

# One transaction per offer may be live or signed at a time.
LIVE_STATUSES = frozenset(
    {
        ESignStatus.INITIATED,
        ESignStatus.PENDING,
        ESignStatus.SIGNED,
        ESignStatus.MANUAL_REVIEW,
    }
)

# Customer-facing labels: no internal detail leaks out.
CUSTOMER_STATUS = {
    ESignStatus.INITIATED: "PENDING",
    ESignStatus.PENDING: "PENDING",
    ESignStatus.SIGNED: "SIGNED",
    ESignStatus.FAILED: "FAILED",
    ESignStatus.EXPIRED: "EXPIRED",
    ESignStatus.MANUAL_REVIEW: "UNDER_REVIEW",
}


def can_transition(current: ESignStatus, new: ESignStatus) -> bool:
    return new in ESIGN_TRANSITIONS[current]


class ESignError(ValueError):
    """Base for e-sign rule violations (still a ValueError)."""


class ESignNotFound(ESignError):
    pass


class ESignConflict(ESignError):
    pass


class ESignUnavailable(ESignError):
    """Provider could not be reached; the outcome is unknown, retry later."""
