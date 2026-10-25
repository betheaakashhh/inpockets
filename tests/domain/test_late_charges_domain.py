from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.domain import late_charges as LC
from app.domain.pricing import LateTerms

T = LateTerms(True, D("4"), D("500"), D("36"), 180, D("40"))
DUE = date(2026, 1, 1)
OVERDUE = D("1617.65")


def on(n):
    return DUE + timedelta(days=n)


def charge(n, *, overdue=OVERDUE, charged=D("0"), terms=T, p_due=D("1617.65"), i_due=D("150.00")):
    return LC.charge_for_day(
        due_date=DUE, on=on(n), overdue_principal=overdue, already_charged=charged,
        principal_due=p_due, interest_due=i_due, terms=terms,
    )


def test_bounce_is_the_lower_of_four_percent_or_the_fixed_cap():
    assert LC.bounce_amount(D("1617.65"), T) == D("64.71")  # 4% is lower
    assert LC.bounce_amount(D("50000"), T) == D("500.00")  # cap is lower
    assert LC.bounce_amount(D("12500"), T) == D("500.00")  # exactly at the cap


def test_day_one_is_bounce_then_daily_penal_on_overdue_principal():
    first = charge(1)
    assert (first.kind, first.amount, first.basis) == (LC.BOUNCE, D("64.71"), D("1617.65"))
    second = charge(2)
    assert (second.kind, second.amount) == (LC.PENAL, D("1.60"))  # 1617.65 x 36% / 365


def test_nothing_before_the_day_after_due_and_nothing_after_the_last_penal_day():
    assert charge(0) is None and charge(-5) is None
    assert charge(180) is not None
    assert charge(181) is None and charge(400) is None


def test_running_total_tracks_the_kreditbee_example_within_pennies():
    total = D("0")
    seen = {}
    for n in range(1, 181):
        c = charge(n, charged=total)
        if c:
            total += c.amount
        seen[n] = total
    # exact (unrounded) figures: 79.07 / 110.98 / 158.84 / 350.31
    for n, exact in ((10, D("79.07")), (30, D("110.98")), (60, D("158.84")), (180, D("350.31"))):
        assert abs(seen[n] - exact) < D("1.00"), (n, seen[n])


def test_total_is_capped_at_forty_percent_of_what_was_due():
    cap = LC.total_cap(D("1617.65"), D("150.00"), T)
    assert cap == D("707.06")
    near = charge(50, charged=cap - D("0.50"))
    assert near.amount == D("0.50")  # only the room left is charged
    assert charge(51, charged=cap) is None


def test_a_tiny_cap_still_never_exceeds_it():
    tight = LateTerms(True, D("4"), D("500"), D("36"), 180, D("1"))
    total = D("0")
    for n in range(1, 181):
        c = charge(n, charged=total, terms=tight)
        if c:
            total += c.amount
    assert total == LC.total_cap(D("1617.65"), D("150.00"), tight)


def test_disabled_or_fully_paid_installments_are_never_charged():
    off = LateTerms(False, D("4"), D("500"), D("36"), 180, D("40"))
    assert charge(1, terms=off) is None
    assert charge(1, overdue=D("0")) is None


def test_penal_charge_follows_the_current_unpaid_principal():
    full = charge(5, overdue=D("1000"))
    half = charge(5, overdue=D("500"))
    assert full.amount == D("0.99") and half.amount == D("0.49")  # 36%/365 per day


def test_days_to_assess_resumes_after_the_last_charged_day_and_stops_at_today():
    assert LC.days_to_assess(DUE, None, on(3), T) == [on(1), on(2), on(3)]
    assert LC.days_to_assess(DUE, on(2), on(4), T) == [on(3), on(4)]
    assert LC.days_to_assess(DUE, on(4), on(4), T) == []
    assert LC.days_to_assess(DUE, None, DUE, T) == []  # due today: not yet overdue
    assert len(LC.days_to_assess(DUE, None, on(1000), T)) == 180  # stops at the last penal day


@pytest.mark.parametrize("n", [1, 2, 90, 180])
def test_charges_are_whole_paise_and_positive(n):
    c = charge(n)
    assert c.amount == c.amount.quantize(D("0.01")) and c.amount > 0
