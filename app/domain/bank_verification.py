from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum


class BankVerificationStatus(StrEnum):
    INITIATED = "INITIATED"  # our record exists; provider outcome not confirmed
    PENDING = "PENDING"  # provider is verifying (e.g. penny drop)
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"  # a human must decide


TRANSITIONS: dict[BankVerificationStatus, frozenset[BankVerificationStatus]] = {
    BankVerificationStatus.INITIATED: frozenset(
        {
            BankVerificationStatus.PENDING,
            BankVerificationStatus.VERIFIED,
            BankVerificationStatus.FAILED,
            BankVerificationStatus.MANUAL_REVIEW,
        }
    ),
    BankVerificationStatus.PENDING: frozenset(
        {
            BankVerificationStatus.VERIFIED,
            BankVerificationStatus.FAILED,
            BankVerificationStatus.MANUAL_REVIEW,
        }
    ),
    # Only a permissioned, audited admin resolution leaves manual review.
    BankVerificationStatus.MANUAL_REVIEW: frozenset(
        {BankVerificationStatus.VERIFIED, BankVerificationStatus.FAILED}
    ),
    BankVerificationStatus.VERIFIED: frozenset(),
    BankVerificationStatus.FAILED: frozenset(),
}

IN_FLIGHT = frozenset(
    {
        BankVerificationStatus.INITIATED,
        BankVerificationStatus.PENDING,
        BankVerificationStatus.MANUAL_REVIEW,
    }
)

CUSTOMER_STATUS = {
    BankVerificationStatus.INITIATED: "PENDING",
    BankVerificationStatus.PENDING: "PENDING",
    BankVerificationStatus.VERIFIED: "VERIFIED",
    BankVerificationStatus.FAILED: "FAILED",
    BankVerificationStatus.MANUAL_REVIEW: "UNDER_REVIEW",
}

# Provider-neutral name match outcomes.
NAME_MATCH_VALUES = frozenset({"MATCH", "PARTIAL", "MISMATCH", "UNAVAILABLE"})

# Failure codes are a closed vocabulary (never free provider text).
# Only these are shown to customers; the rest stay internal so fraud signals
# are not revealed.
CUSTOMER_VISIBLE_FAILURE_CODES = frozenset(
    {"INVALID_ACCOUNT", "ACCOUNT_NOT_FOUND", "NAME_MISMATCH", "PROVIDER_REJECTED"}
)

def utcnow() -> datetime:
    """Single clock for this module (tests fast-forward it)."""
    return datetime.now(UTC)


# Provider failure codes we accept; anything else is stored as VERIFICATION_FAILED.
PROVIDER_FAILURE_CODES = frozenset(
    {
        "INVALID_ACCOUNT",
        "ACCOUNT_NOT_FOUND",
        "ACCOUNT_CLOSED",
        "NAME_MISMATCH",
        "PROVIDER_REJECTED",
        "VERIFICATION_FAILED",
    }
)

ACCOUNT_NUMBER_PATTERN = re.compile(r"^[0-9]{9,18}$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def can_transition(
    current: BankVerificationStatus, new: BankVerificationStatus
) -> bool:
    return new in TRANSITIONS[current]


def mask_account(last4: str) -> str:
    """Fixed-length mask so the account length is not leaked."""
    return f"XXXXXXXX{last4}"


class BankVerificationError(ValueError):
    pass


class BankVerificationNotFound(BankVerificationError):
    pass


class BankVerificationConflict(BankVerificationError):
    pass


class BankVerificationRateLimited(BankVerificationError):
    pass


class BankVerificationUnavailable(BankVerificationError):
    """Provider unreachable; outcome unknown, retry later."""
