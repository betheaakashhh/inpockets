"""2.16 notification rules (pure logic)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain import notifications as n

C, S = n.Category, n.Suppression


@pytest.mark.parametrize(
    "key,cat",
    [("txn.payment_received", C.TRANSACTIONAL), ("support.ticket_received", C.SERVICE),
     ("collections.dpd_1.sms", C.COLLECTIONS), ("marketing.offer.v2", C.MARKETING)],
)
def test_category_comes_from_the_key_prefix(key, cat):
    assert n.category_for_key(key) == cat


@pytest.mark.parametrize("key", ["", "nodot", "Support.x", "other.thing", "support.", ".x", "support.a b", "1support.x"])
def test_bad_template_keys_are_refused(key):
    with pytest.raises(n.NotificationError):
        n.category_for_key(key)


def v(**kw):
    base = dict(key="support.ticket_received", body="Ref {ticket_number}", allowed=["ticket_number"],
                subject=None, channel=n.Channel.SMS)
    base.update(kw)
    return n.validate_template(**base)


def test_valid_template():
    assert v() == C.SERVICE


def test_template_cannot_use_an_undeclared_variable():
    with pytest.raises(n.NotificationError, match="undeclared"):
        v(body="Ref {ticket_number} {secret}")


@pytest.mark.parametrize("body", ["Ref {ticket_number", "Ref ticket_number}", "Ref {Ticket}", "{}", ""])
def test_malformed_placeholders_and_empty_body_are_refused(body):
    with pytest.raises(n.NotificationError):
        v(body=body, allowed=["ticket_number"])


def test_body_length_limit():
    with pytest.raises(n.NotificationError):
        v(body="x" * (n.MAX_BODY + 1), allowed=[])
    assert v(body="x" * n.MAX_BODY, allowed=[])


def test_email_needs_a_subject_and_others_must_not_have_one():
    with pytest.raises(n.NotificationError):
        v(channel=n.Channel.EMAIL)
    assert v(channel=n.Channel.EMAIL, subject="Hello")
    with pytest.raises(n.NotificationError):
        v(subject="Hello")


def test_allowed_variables_must_be_clean_and_unique():
    with pytest.raises(n.NotificationError):
        v(allowed=["ticket_number", "ticket_number"])
    with pytest.raises(n.NotificationError):
        v(allowed=["Bad Name"], body="x")


def test_variables_are_limited_to_the_declared_ones_and_stringified():
    assert n.clean_variables({"a": Decimal("5.00"), "b": 3, "c": "x"}, ["a", "b", "c"]) == {"a": "5.00", "b": "3", "c": "x"}
    with pytest.raises(n.NotificationError):
        n.clean_variables({"a": "1", "extra": "2"}, ["a"])
    for bad in ("two\nlines", "x" * (n.MAX_VALUE + 1), True, ["list"], {"d": 1}):
        with pytest.raises(n.NotificationError):
            n.clean_variables({"a": bad}, ["a"])
    with pytest.raises(n.NotificationError):
        n.clean_variables(["not", "a", "dict"], ["a"])


def test_render_fills_every_placeholder_and_refuses_missing_ones():
    assert n.render("Hi {a}, owe {b}. {a}", {"a": "Asha", "b": "10"}) == "Hi Asha, owe 10. Asha"
    with pytest.raises(n.NotificationError):
        n.render("Hi {a} {b}", {"a": "x"})


def test_values_are_inserted_literally_never_interpreted():
    assert n.render("Hi {a}", {"a": "{b} %s {0}"}) == "Hi {b} %s {0}"


def ok(category, *, active=True, dest=True, pref=None):
    return n.eligibility(category=category, user_active=active, has_destination=dest, preference=pref)


def test_transactional_cannot_be_switched_off():
    assert ok(C.TRANSACTIONAL, pref=False).ok
    assert ok(C.TRANSACTIONAL).ok


def test_service_and_collections_are_on_unless_turned_off():
    for cat in (C.SERVICE, C.COLLECTIONS):
        assert ok(cat).ok and ok(cat, pref=True).ok
        assert ok(cat, pref=False) == n.Eligibility(False, S.OPTED_OUT)


def test_marketing_needs_an_explicit_opt_in():
    assert ok(C.MARKETING) == n.Eligibility(False, S.NOT_OPTED_IN)
    assert ok(C.MARKETING, pref=False) == n.Eligibility(False, S.NOT_OPTED_IN)
    assert ok(C.MARKETING, pref=True).ok


def test_inactive_user_or_missing_destination_always_blocks():
    for cat in C:
        assert ok(cat, active=False, pref=True) == n.Eligibility(False, S.USER_NOT_ACTIVE)
        assert ok(cat, dest=False, pref=True) == n.Eligibility(False, S.NO_DESTINATION)


def test_backoff_grows_and_is_capped():
    delays = [n.backoff_for(i) for i in range(1, 8)]
    assert delays[0] == timedelta(minutes=1) and delays == sorted(delays)
    assert delays[-1] == delays[len(n.BACKOFF) - 1] == n.BACKOFF[-1]
    assert n.backoff_for(0) == n.BACKOFF[0]
