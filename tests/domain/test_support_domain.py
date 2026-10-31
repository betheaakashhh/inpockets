"""2.17 support rules (pure)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain import support as s

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("cur,new,ok", [
    ("OPEN", "IN_PROGRESS", True), ("OPEN", "WAITING_ON_CUSTOMER", True), ("OPEN", "RESOLVED", True),
    ("OPEN", "CLOSED", False), ("OPEN", "OPEN", False),
    ("IN_PROGRESS", "WAITING_ON_CUSTOMER", True), ("IN_PROGRESS", "RESOLVED", True),
    ("IN_PROGRESS", "OPEN", False), ("IN_PROGRESS", "CLOSED", False),
    ("WAITING_ON_CUSTOMER", "IN_PROGRESS", True), ("WAITING_ON_CUSTOMER", "RESOLVED", True),
    ("WAITING_ON_CUSTOMER", "CLOSED", False),
    ("RESOLVED", "IN_PROGRESS", True), ("RESOLVED", "CLOSED", True), ("RESOLVED", "OPEN", False),
    ("CLOSED", "IN_PROGRESS", False), ("CLOSED", "OPEN", False), ("CLOSED", "RESOLVED", False),
])
def test_transitions(cur, new, ok):
    assert s.can_transition(s.Status(cur), s.Status(new)) is ok


def test_every_status_has_a_rule_and_closed_is_final():
    assert set(s.TRANSITIONS) == set(s.Status)
    assert s.TRANSITIONS[s.Status.CLOSED] == frozenset()


def test_sensitive_categories():
    assert s.is_sensitive(s.Category.FRAUD_OR_UNAUTHORISED) and s.is_sensitive(s.Category.DATA_PRIVACY)
    assert not any(s.is_sensitive(c) for c in s.Category
                   if c not in (s.Category.FRAUD_OR_UNAUTHORISED, s.Category.DATA_PRIVACY))


def test_customers_never_see_internal_event_kinds():
    hidden = set(s.EventType) - s.CUSTOMER_VISIBLE
    assert {s.EventType.INTERNAL_NOTE, s.EventType.ASSIGNED, s.EventType.ESCALATED,
            s.EventType.CONTACT_REVEALED, s.EventType.PRIORITY_CHANGED} <= hidden


def test_customer_reply_rules():
    for st in s.LIVE:
        assert s.customer_can_reply(st, None, NOW)
    assert s.customer_can_reply(s.Status.RESOLVED, NOW - timedelta(days=6), NOW)
    assert s.customer_can_reply(s.Status.RESOLVED, NOW - s.REOPEN_WINDOW, NOW)
    assert not s.customer_can_reply(s.Status.RESOLVED, NOW - timedelta(days=8), NOW)
    assert not s.customer_can_reply(s.Status.RESOLVED, None, NOW)
    assert not s.customer_can_reply(s.Status.CLOSED, NOW, NOW)


def test_sla_only_for_complaints_and_overdue_only_when_live():
    assert s.sla_due(s.Kind.QUESTION, NOW, 30) is None and s.sla_due(s.Kind.ISSUE, NOW, 30) is None
    due = s.sla_due(s.Kind.COMPLAINT, NOW, 30)
    assert due == NOW + timedelta(days=30)
    assert not s.is_overdue(s.Status.OPEN, due, due)  # on the deadline is not late
    assert s.is_overdue(s.Status.OPEN, due, due + timedelta(seconds=1))
    assert s.is_overdue(s.Status.WAITING_ON_CUSTOMER, due, due + timedelta(days=1))
    assert not s.is_overdue(s.Status.RESOLVED, due, due + timedelta(days=1))
    assert not s.is_overdue(s.Status.CLOSED, due, due + timedelta(days=1))
    assert not s.is_overdue(s.Status.OPEN, None, NOW)


@pytest.mark.parametrize("phone,masked", [
    ("+919876543210", "*********3210"), ("1234", "1234"), ("12", "12"), ("", ""), (None, ""),
])
def test_mask_phone(phone, masked):
    assert s.mask_phone(phone) == masked


def test_ticket_number_format():
    assert s.format_ticket_number(7, date(2026, 3, 1)) == "INP-2026-000007"
    assert s.format_ticket_number(1234567, date(2027, 1, 1)) == "INP-2027-1234567"
