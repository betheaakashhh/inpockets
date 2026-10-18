
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.loan_offer import (
    LoanOffer,
    LoanOfferStatus,
    LoanOfferTerms,
)


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def make_terms() -> LoanOfferTerms:
    return LoanOfferTerms(
        principal_amount=Decimal("25000.00"),
        tenure_days=90,
        commercial_terms={
            "annual_interest_rate": "18.00",
            "processing_fee": "500.00",
            "currency": "INR",
            "repayment_frequency": "MONTHLY",
        },
    )


def make_offer(
    *,
    status: LoanOfferStatus = LoanOfferStatus.DRAFT,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    accepted_at: datetime | None = None,
    version: int = 1,
) -> LoanOffer:
    return LoanOffer(
        id=uuid4(),
        loan_application_id=uuid4(),
        user_id=uuid4(),
        version=version,
        terms=make_terms(),
        status=status,
        issued_at=issued_at,
        expires_at=expires_at,
        accepted_at=accepted_at,
    )


def test_valid_offer_terms_are_accepted() -> None:
    terms = make_terms()

    assert terms.principal_amount == Decimal("25000.00")
    assert terms.tenure_days == 90
    assert terms.commercial_terms["currency"] == "INR"


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("-1.00"),
        Decimal("10.001"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_invalid_principal_amount_is_rejected(
    amount: Decimal,
) -> None:
    with pytest.raises(ValueError):
        LoanOfferTerms(
            principal_amount=amount,
            tenure_days=30,
            commercial_terms={},
        )


def test_non_positive_tenure_is_rejected() -> None:
    with pytest.raises(ValueError, match="tenure must be positive"):
        LoanOfferTerms(
            principal_amount=Decimal("1000.00"),
            tenure_days=0,
            commercial_terms={},
        )


def test_non_dictionary_commercial_terms_are_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="commercial terms must be a dictionary",
    ):
        LoanOfferTerms(
            principal_amount=Decimal("1000.00"),
            tenure_days=30,
            commercial_terms=[],  # type: ignore[arg-type]
        )


def test_draft_offer_must_not_have_issue_or_expiry_times() -> None:
    with pytest.raises(ValueError, match="draft offers"):
        make_offer(
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )


def test_issued_offer_requires_issue_and_expiry_times() -> None:
    with pytest.raises(ValueError, match="issue and expiry timestamps"):
        make_offer(status=LoanOfferStatus.ISSUED)


def test_expiry_must_be_after_issue_time() -> None:
    with pytest.raises(ValueError, match="expiry must be after issue time"):
        make_offer(
            status=LoanOfferStatus.ISSUED,
            issued_at=NOW,
            expires_at=NOW,
        )


def test_issued_offer_with_valid_expiry_is_accepted() -> None:
    offer = make_offer(
        status=LoanOfferStatus.ISSUED,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )

    assert offer.status == LoanOfferStatus.ISSUED


def test_offer_version_must_be_positive() -> None:
    with pytest.raises(ValueError, match="version must be at least 1"):
        make_offer(version=0)


def test_accepted_offer_requires_acceptance_timestamp() -> None:
    with pytest.raises(ValueError, match="acceptance timestamp"):
        make_offer(
            status=LoanOfferStatus.ACCEPTED,
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )


def test_acceptance_must_be_before_expiry() -> None:
    with pytest.raises(ValueError, match="before offer expiry"):
        make_offer(
            status=LoanOfferStatus.ACCEPTED,
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
            accepted_at=NOW + timedelta(days=7),
        )


def test_acceptance_cannot_precede_issuance() -> None:
    with pytest.raises(ValueError, match="cannot precede issue time"):
        make_offer(
            status=LoanOfferStatus.ACCEPTED,
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
            accepted_at=NOW - timedelta(seconds=1),
        )


def test_non_accepted_offer_cannot_have_acceptance_timestamp() -> None:
    with pytest.raises(
        ValueError,
        match="only accepted offers",
    ):
        make_offer(
            status=LoanOfferStatus.ISSUED,
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
            accepted_at=NOW + timedelta(hours=1),
        )


def test_accepted_offer_with_valid_timestamps_is_accepted() -> None:
    offer = make_offer(
        status=LoanOfferStatus.ACCEPTED,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=7),
        accepted_at=NOW + timedelta(hours=1),
    )

    assert offer.status == LoanOfferStatus.ACCEPTED
    assert offer.accepted_at == NOW + timedelta(hours=1)
