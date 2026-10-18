
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


def utcnow() -> datetime:
    """The one clock for offer expiry logic (patched in tests)."""
    return datetime.now(timezone.utc)


class LoanOfferError(ValueError):
    """Base class for loan-offer rule violations (still a ValueError)."""


class LoanOfferNotFound(LoanOfferError):
    """Offer does not exist or is not visible to the caller."""


class LoanOfferConflict(LoanOfferError):
    """Request conflicts with the offer's current state or terms."""


class LoanOfferStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


# Statuses in which an offer is live for a customer. At most one offer per
# application may be in one of these states (enforced by a partial unique index).
OPEN_OFFER_STATUSES = frozenset(
    {LoanOfferStatus.ISSUED, LoanOfferStatus.ACCEPTED}
)


def effective_offer_status(
    *,
    status: str,
    expires_at: datetime | None,
    now: datetime,
) -> str:
    """Customer-facing status: an ISSUED offer past expiry reads as EXPIRED.

    The stored status is only flipped by an explicit transition/worker, so
    reads must not show an offer as actionable once its window has closed.
    """
    if (
        status == LoanOfferStatus.ISSUED.value
        and expires_at is not None
        and now >= expires_at
    ):
        return LoanOfferStatus.EXPIRED.value
    return status


@dataclass(frozen=True, slots=True)
class LoanOfferTerms:
    """Immutable snapshot of the commercial terms for one offer version."""

    principal_amount: Decimal
    tenure_days: int
    commercial_terms: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.principal_amount.is_finite():
            raise ValueError("principal amount must be finite")

        if self.principal_amount <= Decimal("0"):
            raise ValueError("principal amount must be positive")

        if self.principal_amount.as_tuple().exponent < -2:
            raise ValueError(
                "principal amount cannot have more than two decimal places"
            )

        if self.tenure_days <= 0:
            raise ValueError("tenure must be positive")

        if not isinstance(self.commercial_terms, dict):
            raise ValueError("commercial terms must be a dictionary")


@dataclass(frozen=True, slots=True)
class LoanOffer:
    """Domain representation of a versioned loan offer."""

    id: UUID
    loan_application_id: UUID
    user_id: UUID
    version: int
    terms: LoanOfferTerms
    status: LoanOfferStatus
    issued_at: datetime | None
    expires_at: datetime | None
    accepted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("offer version must be at least 1")

        if self.status == LoanOfferStatus.DRAFT:
            if self.issued_at is not None or self.expires_at is not None:
                raise ValueError(
                    "draft offers must not have issue or expiry timestamps"
                )

        if self.status in {
            LoanOfferStatus.ISSUED,
            LoanOfferStatus.ACCEPTED,
            LoanOfferStatus.DECLINED,
            LoanOfferStatus.EXPIRED,
        }:
            if self.issued_at is None or self.expires_at is None:
                raise ValueError(
                    "issued offers must have issue and expiry timestamps"
                )

        if self.issued_at is not None and self.expires_at is not None:
            if self.issued_at.utcoffset() is None:
                raise ValueError("issue timestamp must be timezone-aware")

            if self.expires_at.utcoffset() is None:
                raise ValueError("expiry timestamp must be timezone-aware")

            if self.expires_at <= self.issued_at:
                raise ValueError("expiry must be after issue time")

        if self.status == LoanOfferStatus.ACCEPTED:
            if self.accepted_at is None:
                raise ValueError(
                    "accepted offers must have an acceptance timestamp"
                )

            if self.accepted_at.utcoffset() is None:
                raise ValueError(
                    "acceptance timestamp must be timezone-aware"
                )

            if self.issued_at is not None and self.accepted_at < self.issued_at:
                raise ValueError(
                    "acceptance cannot precede issue time"
                )

            if self.expires_at is not None and self.accepted_at >= self.expires_at:
                raise ValueError(
                    "acceptance must occur before offer expiry"
                )
        elif self.accepted_at is not None:
            raise ValueError(
                "only accepted offers may have an acceptance timestamp"
            )
