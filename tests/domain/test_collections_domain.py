"""2.15 collections rules (pure logic): DPD boundaries, buckets, reminders, escalation."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.domain import collections as c

D = Decimal
DUE = date(2026, 6, 10)


def inst(n, due, p="1000.00", i="100.00", f="0.00", pp="0", ip="0", fp="0"):
    return c.InstallmentView(
        id=f"i{n}", number=n, due_date=due,
        principal_outstanding=D(p) - D(pp), interest_outstanding=D(i) - D(ip),
        fee_outstanding=D(f) - D(fp),
    )


@pytest.mark.parametrize(
    "dpd,bucket",
    [(-5, None), (0, None), (1, "1-7"), (7, "1-7"), (8, "8-30"), (30, "8-30"), (31, "31-60"),
     (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "91+"), (1000, "91+")],
)
def test_bucket_boundaries(dpd, bucket):
    assert c.bucket_for(dpd) == bucket


def test_every_bucket_range_is_contiguous():
    assert c.bucket_range("1-7") == (1, 7)
    assert c.bucket_range("8-30") == (8, 30)
    assert c.bucket_range("91+") == (91, None)
    with pytest.raises(c.CollectionsError):
        c.bucket_range("nope")


def test_not_overdue_on_the_due_date_but_dpd_1_the_day_after():
    assert c.overdue_of([inst(1, DUE)], DUE) is None
    assert c.overdue_of([inst(1, DUE)], DUE - timedelta(days=3)) is None
    o = c.overdue_of([inst(1, DUE)], DUE + timedelta(days=1))
    assert o.dpd == 1 and o.oldest_installment_id == "i1"


@pytest.mark.parametrize("days", [1, 7, 8, 30, 31, 60, 61, 90, 91, 400])
def test_dpd_counts_whole_days_since_the_due_date(days):
    assert c.overdue_of([inst(1, DUE)], DUE + timedelta(days=days)).dpd == days


def test_dpd_is_measured_from_the_oldest_unpaid_installment():
    rows = [inst(1, DUE), inst(2, DUE + timedelta(days=30))]
    o = c.overdue_of(rows, DUE + timedelta(days=45))
    assert o.dpd == 45 and o.oldest_installment_id == "i1"
    assert o.principal == D("2000.00") and o.interest == D("200.00")


def test_a_paid_older_installment_moves_dpd_to_the_next_one():
    rows = [inst(1, DUE, pp="1000", ip="100"), inst(2, DUE + timedelta(days=30))]
    o = c.overdue_of(rows, DUE + timedelta(days=45))
    assert o.dpd == 15 and o.oldest_installment_id == "i2"


def test_a_partly_paid_installment_is_still_overdue_with_the_remainder():
    o = c.overdue_of([inst(1, DUE, pp="400")], DUE + timedelta(days=2))
    assert o.principal == D("600.00") and o.interest == D("100.00")


def test_only_late_charges_outstanding_is_not_overdue():
    paid = inst(1, DUE, f="50.00", pp="1000", ip="100")
    assert paid.fee_outstanding == D("50.00")
    assert c.overdue_of([paid], DUE + timedelta(days=20)) is None


def test_overdue_fees_are_reported_alongside():
    o = c.overdue_of([inst(1, DUE, f="64.71")], DUE + timedelta(days=1))
    assert o.fees == D("64.71") and o.total == D("1164.71")


def test_only_the_installments_that_are_due_count():
    rows = [inst(1, DUE), inst(2, DUE + timedelta(days=30))]
    o = c.overdue_of(rows, DUE + timedelta(days=5))
    assert o.principal == D("1000.00")


@pytest.mark.parametrize(
    "dpd,milestone",
    [(0, None), (1, 1), (2, 1), (3, 3), (6, 3), (7, 7), (14, 7), (15, 15), (29, 15), (30, 30), (200, 30)],
)
def test_only_the_latest_reached_reminder_milestone_is_due(dpd, milestone):
    assert c.due_reminder_milestone(dpd) == milestone


def test_reminder_keys_are_unique_per_installment_milestone_and_channel():
    a = c.reminder_key("i1", 3, c.Channel.SMS)
    assert a == c.reminder_key("i1", 3, c.Channel.SMS)
    assert len({a, c.reminder_key("i2", 3, c.Channel.SMS), c.reminder_key("i1", 7, c.Channel.SMS),
                c.reminder_key("i1", 3, c.Channel.PUSH)}) == 4


def test_call_is_not_a_reminder_channel():
    assert c.Channel.CALL not in c.REMINDER_CHANNELS
    assert all(ch in c.REMINDER_CHANNELS for chans in c.REMINDER_MILESTONES.values() for ch in chans)


@pytest.mark.parametrize(
    "dpd,level",
    [(0, 0), (29, 0), (30, 1), (59, 1), (60, 2), (89, 2), (90, 3), (500, 3)],
)
def test_escalation_levels_at_the_thresholds(dpd, level):
    assert c.escalation_level_for(dpd) == level
