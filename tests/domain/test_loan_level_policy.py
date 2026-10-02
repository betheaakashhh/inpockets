from decimal import Decimal

from app.domain.loan_level import LoanLevel
from app.domain.loan_level_policy import LoanLevelPolicyConstraint


def make_level() -> LoanLevel:
    return LoanLevel(
        code="LEVEL_1",
        name="Starter",
        min_amount=Decimal("1000"),
        max_amount=Decimal("10000"),
        min_tenure_days=7,
        max_tenure_days=30,
    )


def test_valid_application_satisfies_loan_level_constraint():
    result = LoanLevelPolicyConstraint().validate(
        loan_level=make_level(),
        requested_amount=Decimal("5000"),
        requested_tenure_days=15,
    )

    assert result.loan_level_code == "LEVEL_1"
    assert result.amount_valid is True
    assert result.tenure_valid is True
    assert result.valid is True


def test_amount_outside_level_is_invalid():
    result = LoanLevelPolicyConstraint().validate(
        loan_level=make_level(),
        requested_amount=Decimal("15000"),
        requested_tenure_days=15,
    )

    assert result.amount_valid is False
    assert result.tenure_valid is True
    assert result.valid is False


def test_tenure_outside_level_is_invalid():
    result = LoanLevelPolicyConstraint().validate(
        loan_level=make_level(),
        requested_amount=Decimal("5000"),
        requested_tenure_days=45,
    )

    assert result.amount_valid is True
    assert result.tenure_valid is False
    assert result.valid is False


def test_amount_and_tenure_are_both_required():
    result = LoanLevelPolicyConstraint().validate(
        loan_level=make_level(),
        requested_amount=Decimal("15000"),
        requested_tenure_days=45,
    )

    assert result.amount_valid is False
    assert result.tenure_valid is False
    assert result.valid is False