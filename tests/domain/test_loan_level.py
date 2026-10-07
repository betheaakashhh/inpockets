from decimal import Decimal

import pytest

from app.domain.loan_level import LoanLevel


def make_level() -> LoanLevel:
    return LoanLevel(
        code="LEVEL_1",
        name="Starter",
        min_amount=Decimal("1000"),
        max_amount=Decimal("10000"),
        min_tenure_days=7,
        max_tenure_days=30,
        description="Starter lending level",
    )


def test_loan_level_accepts_valid_configuration():
    level = make_level()

    assert level.code == "LEVEL_1"
    assert level.name == "Starter"
    assert level.min_amount == Decimal("1000")
    assert level.max_amount == Decimal("10000")


def test_amount_boundaries_are_inclusive():
    level = make_level()

    assert level.supports_amount(Decimal("1000"))
    assert level.supports_amount(Decimal("10000"))
    assert not level.supports_amount(Decimal("999.99"))
    assert not level.supports_amount(Decimal("10000.01"))


def test_tenure_boundaries_are_inclusive():
    level = make_level()

    assert level.supports_tenure(7)
    assert level.supports_tenure(30)
    assert not level.supports_tenure(6)
    assert not level.supports_tenure(31)


def test_supports_combines_amount_and_tenure_constraints():
    level = make_level()

    assert level.supports(
        amount=Decimal("5000"),
        tenure_days=15,
    )

    assert not level.supports(
        amount=Decimal("500"),
        tenure_days=15,
    )

    assert not level.supports(
        amount=Decimal("5000"),
        tenure_days=60,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", ""),
        ("name", ""),
    ],
)
def test_required_text_fields_are_validated(field, value):
    kwargs = {
        "code": "LEVEL_1",
        "name": "Starter",
        "min_amount": Decimal("1000"),
        "max_amount": Decimal("10000"),
        "min_tenure_days": 7,
        "max_tenure_days": 30,
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        LoanLevel(**kwargs)


def test_amount_range_must_be_valid():
    with pytest.raises(ValueError, match="max_amount"):
        LoanLevel(
            code="LEVEL_1",
            name="Starter",
            min_amount=Decimal("10000"),
            max_amount=Decimal("1000"),
            min_tenure_days=7,
            max_tenure_days=30,
        )


def test_tenure_range_must_be_valid():
    with pytest.raises(ValueError, match="max_tenure_days"):
        LoanLevel(
            code="LEVEL_1",
            name="Starter",
            min_amount=Decimal("1000"),
            max_amount=Decimal("10000"),
            min_tenure_days=30,
            max_tenure_days=7,
        )


def test_min_amount_must_be_positive():
    with pytest.raises(ValueError, match="min_amount"):
        LoanLevel(
            code="LEVEL_1",
            name="Starter",
            min_amount=Decimal("0"),
            max_amount=Decimal("10000"),
            min_tenure_days=7,
            max_tenure_days=30,
        )


def test_min_tenure_must_be_positive():
    with pytest.raises(ValueError, match="min_tenure_days"):
        LoanLevel(
            code="LEVEL_1",
            name="Starter",
            min_amount=Decimal("1000"),
            max_amount=Decimal("10000"),
            min_tenure_days=0,
            max_tenure_days=30,
        )