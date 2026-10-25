from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain import repayment as R
from app.domain.repayment import (
    InstallmentState,
    PaymentStatus as S,
    RepaymentError,
    allocate,
    build_schedule,
)

D = Decimal
START = date(2026, 1, 1)


def inst(n, principal="100.00", interest="0.00", fee="0.00", pp="0.00", ip="0.00", fp="0.00"):
    return InstallmentState(
        id=uuid4(), number=n, due_date=START + timedelta(days=30 * n),
        principal_due=D(principal), interest_due=D(interest), fee_due=D(fee),
        principal_paid=D(pp), interest_paid=D(ip), fee_paid=D(fp),
    )


# ---------------------------------------------------------------- schedule


def test_equal_principal_sums_exactly_with_remainder_on_last():
    plans = build_schedule(principal=D("100.00"), count=3, start=START, interval_days=10)
    assert [p.principal_due for p in plans] == [D("33.33"), D("33.33"), D("33.34")]
    assert sum(p.principal_due for p in plans) == D("100.00")
    assert [p.due_date for p in plans] == [date(2026, 1, 11), date(2026, 1, 21), date(2026, 1, 31)]
    assert all(p.interest_due == 0 and p.fee_due == 0 for p in plans)


@pytest.mark.parametrize("principal,count", [("5000.00", 7), ("10000.01", 12), ("1.00", 60), ("999.99", 11)])
def test_principal_always_sums_exactly(principal, count):
    plans = build_schedule(principal=D(principal), count=count, start=START, interval_days=7)
    assert sum(p.principal_due for p in plans) == D(principal)
    assert all(p.principal_due > 0 for p in plans)


def test_interest_only_when_a_rate_is_given_and_is_on_outstanding_principal():
    plans = build_schedule(
        principal=D("1000.00"), count=2, start=START, interval_days=30, annual_rate_percent=D("36.5")
    )
    # 1000 * 36.5% * 30/365 = 30.00; then 500 outstanding -> 15.00
    assert [p.interest_due for p in plans] == [D("30.00"), D("15.00")]
    assert all(p.fee_due == 0 for p in plans)  # fees are never generated


def test_a_principal_too_small_to_split_is_rejected():
    with pytest.raises(RepaymentError):
        build_schedule(principal=D("0.10"), count=11, start=START, interval_days=7)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(principal=D("0"), count=1, interval_days=30),
        dict(principal=D("100"), count=0, interval_days=30),
        dict(principal=D("100"), count=61, interval_days=30),
        dict(principal=D("100"), count=1, interval_days=0),
        dict(principal=D("100"), count=1, interval_days=366),
    ],
)
def test_invalid_schedule_inputs_are_rejected(kwargs):
    with pytest.raises(RepaymentError):
        build_schedule(start=START, **kwargs)


# -------------------------------------------------------------- allocation


def test_oldest_first_and_fees_then_interest_then_principal():
    items = [inst(2, "100", "10", "5"), inst(1, "100", "10", "5")]  # given out of order
    allocs, rest = allocate(items, D("20.00"))
    assert rest == 0
    assert len(allocs) == 1  # 20 is fully absorbed by installment 1
    (first,) = allocs
    assert first.installment_id == items[1].id  # installment 1 first
    assert (first.fee, first.interest, first.principal) == (D("5.00"), D("10.00"), D("5.00"))

    # A bigger payment spills into installment 2 in the same order.
    allocs, rest = allocate(items, D("130.00"))
    assert [a.installment_id for a in allocs] == [items[1].id, items[0].id]
    assert (allocs[0].fee, allocs[0].interest, allocs[0].principal) == (D("5"), D("10"), D("100"))
    assert (allocs[1].fee, allocs[1].interest, allocs[1].principal) == (D("5"), D("10"), D("0"))
    assert rest == 0


def test_partial_payment_leaves_remainder_due():
    items = [inst(1, "100")]
    allocs, rest = allocate(items, D("40.00"))
    assert rest == 0 and allocs[0].principal == D("40.00")
    items[0].principal_paid += allocs[0].principal
    assert items[0].outstanding == D("60.00")
    assert R.stored_status(items[0]) == R.InstallmentStatus.PARTIALLY_PAID


def test_early_payment_goes_to_the_earliest_unpaid_even_if_not_yet_due():
    items = [inst(1), inst(2), inst(3)]
    allocs, rest = allocate(items, D("150.00"))
    assert rest == 0
    assert [(a.installment_id, a.principal) for a in allocs] == [
        (items[0].id, D("100.00")),
        (items[1].id, D("50.00")),
    ]


def test_payment_beyond_outstanding_returns_the_excess_as_unapplied():
    items = [inst(1, "100"), inst(2, "100")]
    allocs, rest = allocate(items, D("250.00"))
    assert sum(a.total for a in allocs) == D("200.00")
    assert rest == D("50.00")


def test_already_paid_installments_are_skipped():
    items = [inst(1, "100", pp="100.00"), inst(2, "100")]
    allocs, rest = allocate(items, D("30.00"))
    assert [a.installment_id for a in allocs] == [items[1].id]
    assert rest == 0


def test_allocation_never_exceeds_what_is_due_per_component():
    items = [inst(1, "100", "10", "5", pp="60.00", ip="10.00", fp="0.00")]
    allocs, rest = allocate(items, D("1000.00"))
    a = allocs[0]
    assert (a.fee, a.interest, a.principal) == (D("5.00"), D("0.00"), D("40.00"))
    assert rest == D("955.00")


def test_status_helpers():
    assert R.stored_status(inst(1)) == R.InstallmentStatus.SCHEDULED
    assert R.stored_status(inst(1, pp="100.00")) == R.InstallmentStatus.PAID
    due = date(2026, 3, 1)
    assert R.effective_status("SCHEDULED", due, date(2026, 3, 1)) == "SCHEDULED"  # due today: not late
    assert R.effective_status("SCHEDULED", due, date(2026, 3, 2)) == "OVERDUE"
    assert R.effective_status("PARTIALLY_PAID", due, date(2026, 3, 2)) == "OVERDUE"
    assert R.effective_status("PAID", due, date(2026, 3, 2)) == "PAID"


def test_today_in_ist_rolls_over_at_1830_utc():
    before = datetime(2026, 5, 1, 18, 29, tzinfo=timezone.utc)
    after = datetime(2026, 5, 1, 18, 30, tzinfo=timezone.utc)
    assert R.today_ist(before) == date(2026, 5, 1)
    assert R.today_ist(after) == date(2026, 5, 2)


# ------------------------------------------------------------ state machine


def test_payment_transitions():
    assert R.can_transition(S.INITIATED, S.PENDING)
    assert R.can_transition(S.PENDING, S.SUCCESS)
    assert R.can_transition(S.SUCCESS, S.REVERSED)
    assert R.can_transition(S.FAILED, S.REQUIRES_REVIEW)
    assert R.can_transition(S.REQUIRES_REVIEW, S.SUCCESS)
    for bad in (
        (S.SUCCESS, S.FAILED), (S.SUCCESS, S.PENDING), (S.FAILED, S.SUCCESS),
        (S.REVERSED, S.SUCCESS), (S.REVERSED, S.REQUIRES_REVIEW), (S.PENDING, S.INITIATED),
    ):
        assert not R.can_transition(*bad)


def test_every_status_has_a_customer_label_and_no_internal_leak():
    assert set(R.CUSTOMER_STATUS) == set(S)
    assert set(R.CUSTOMER_STATUS.values()) == {"PROCESSING", "PAID", "FAILED", "REVERSED"}
