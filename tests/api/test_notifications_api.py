"""2.16 notifications on real Postgres with the development provider."""

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

import app.services.notifications as notif_service
from app.core.config import get_settings
from app.domain.repayment import utcnow
from app.main import app
from app.models.audit_log import AuditLog
from app.models.notification import Notification, NotificationAttempt
from app.models.user import User
from app.providers.notification_development import DevelopmentNotificationProvider as Prov, sign_webhook
from app.services.notifications_factory import build_notification_service
from app.workers.notifications import run_once as run_worker
from types import SimpleNamespace

from tests.api.test_loan_offer_api import make_actor as _make_actor
from tests.api.test_loan_offer_api import world  # noqa: F401
from tests.api.test_disbursement_api import ready  # noqa: F401
from tests.api.test_repayment_api import env  # noqa: F401

client = TestClient(app)
SECRET = "notification-test-secret"
BASE = "/api/v1/admin/notifications"
CUSTOMER = "/api/v1/notifications"


@pytest.fixture(autouse=True)
def notif_env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "notification_webhook_secret", SECRET)
    monkeypatch.setattr(s, "rate_limit_sensitive_per_minute", 1000)
    monkeypatch.setattr(s, "rate_limit_user_per_minute", 1000)
    monkeypatch.setattr(s, "rate_limit_webhook_per_minute", 1000)
    Prov.reset()
    yield
    Prov.reset()


# ------------------------------------------------------------- helpers


async def make_actor(monkeypatch, db_session, *, role=None):
    row, headers = await _make_actor(monkeypatch, db_session, role=role)
    return SimpleNamespace(id=row.id, phone_number=row.phone_number), headers


async def staff(monkeypatch, db_session):
    _, finance = await make_actor(monkeypatch, db_session, role="FINANCE")
    _, boss = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    _, support = await make_actor(monkeypatch, db_session, role="CUSTOMER_SUPPORT")
    _, agent = await make_actor(monkeypatch, db_session, role="COLLECTIONS_AGENT")
    return finance, boss, support, agent


def create_template(h, key="support.ticket_received", channel="SMS", body="Request {ticket_number} received.",
                    variables=("ticket_number",), **extra):
    return client.post(f"{BASE}/templates", headers=h, json={
        "template_key": key, "channel": channel, "body": body, "allowed_variables": list(variables), **extra})


def live_template(finance, boss, **kw):
    made = create_template(finance, **kw)
    assert made.status_code == 201, made.text
    done = client.post(f"{BASE}/templates/{made.json()['id']}/approve", headers=boss)
    assert done.status_code == 200, done.text
    return done.json()


async def enqueue(db_session, user_id, key="support.ticket_received", channel="SMS", variables=None, dedupe=None):
    res = await build_notification_service(db_session).enqueue(
        user_id=user_id, template_key=key, channel=channel,
        variables={"ticket_number": "T-1"} if variables is None else variables, dedupe_key=dedupe)
    await db_session.commit()
    return res


async def row(db_session, nid):
    db_session.expire_all()
    return (await db_session.execute(select(Notification).where(Notification.id == nid))).scalar_one()


async def attempts(db_session, nid):
    db_session.expire_all()
    return [a.outcome for a in (await db_session.execute(
        select(NotificationAttempt).where(NotificationAttempt.notification_id == nid)
        .order_by(NotificationAttempt.created_at, NotificationAttempt.attempt_no))).scalars()]


async def audit(db_session):
    return [a for (a,) in await db_session.execute(select(AuditLog.action))]


def receipt(ref, status, *, event_id=None, secret=SECRET):
    body = json.dumps({"event_id": event_id or f"evt-{uuid4()}", "provider_ref": ref, "status": status,
                       "occurred_at": utcnow().isoformat()}).encode()
    headers = sign_webhook(secret, body) if secret else {}
    headers["Content-Type"] = "application/json"
    return client.post("/api/v1/webhooks/notification/development", content=body, headers=headers)


def forward(monkeypatch, **delta):
    real = notif_service.utcnow
    monkeypatch.setattr(notif_service, "utcnow", lambda: real() + timedelta(**delta))


# ------------------------------------------------------------ templates


async def test_template_lifecycle_and_maker_checker(monkeypatch, db_session):
    finance, boss, support, agent = await staff(monkeypatch, db_session)
    made = create_template(finance)
    assert made.status_code == 201
    t = made.json()
    assert (t["status"], t["version"], t["category"]) == ("DRAFT", 1, "SERVICE")
    # the author's role cannot approve; a different admin must
    assert client.post(f"{BASE}/templates/{t['id']}/approve", headers=finance).status_code == 403
    assert client.post(f"{BASE}/templates/{t['id']}/approve", headers=support).status_code == 403
    approved = client.post(f"{BASE}/templates/{t['id']}/approve", headers=boss)
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert client.post(f"{BASE}/templates/{t['id']}/approve", headers=boss).status_code == 409
    assert client.post(f"{BASE}/templates/{t['id']}/reject", headers=boss).status_code == 409
    # a super admin who wrote a template cannot approve it themselves
    own = create_template(boss, key="support.ticket_replied").json()
    assert client.post(f"{BASE}/templates/{own['id']}/approve", headers=boss).status_code == 409
    rejected = create_template(finance, key="support.ticket_resolved").json()
    assert client.post(f"{BASE}/templates/{rejected['id']}/reject", headers=boss).json()["status"] == "REJECTED"
    acts = await audit(db_session)
    for a in ("NOTIFICATION_TEMPLATE_CREATED", "NOTIFICATION_TEMPLATE_APPROVED", "NOTIFICATION_TEMPLATE_REJECTED"):
        assert a in acts
    listed = client.get(f"{BASE}/templates?key=support.ticket_received", headers=support)
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert client.get(f"{BASE}/templates", headers=agent).status_code == 403


async def test_template_validation_errors_are_clean_400s(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    assert create_template(finance, key="bad key").status_code == 400
    assert create_template(finance, key="other.thing").status_code == 400
    assert create_template(finance, body="Hi {nope}").status_code == 400
    assert create_template(finance, channel="EMAIL").status_code == 400
    assert create_template(finance, channel="FAX").status_code == 422
    assert create_template(finance, channel="EMAIL", subject="Hello").status_code == 201
    assert client.post(f"{BASE}/templates", headers=finance, json={"template_key": "support.x", "channel": "SMS",
                       "body": "x", "allowed_variables": [], "surprise": 1}).status_code == 422


async def test_template_selection_uses_the_latest_approved_version(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    customer, _h = await make_actor(monkeypatch, db_session)
    live_template(finance, boss, body="Version one {ticket_number}")
    v2 = live_template(finance, boss, body="Version two {ticket_number}")
    draft = create_template(finance, body="Version three {ticket_number}").json()
    assert (v2["version"], draft["version"]) == (2, 3)
    res = await enqueue(db_session, customer.id)
    n = await row(db_session, res.notification_id)
    assert n.template_version == 2  # the draft v3 is not used
    await run_worker()
    assert next(iter(Prov.sent.values()))["body"] == "Version two T-1"
    # approving v3 later does not change what the already-created message used
    client.post(f"{BASE}/templates/{draft['id']}/approve", headers=boss)
    assert (await row(db_session, res.notification_id)).template_version == 2


async def test_selection_is_per_channel_and_an_unapproved_template_suppresses(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    customer, _h = await make_actor(monkeypatch, db_session)
    create_template(finance)  # draft only
    res = await enqueue(db_session, customer.id)
    n = await row(db_session, res.notification_id)
    assert (n.status, n.suppress_reason, n.template_version) == ("SUPPRESSED", "NO_APPROVED_TEMPLATE", None)
    live_template(finance, boss, channel="SMS", key="support.ticket_replied", body="Reply {ticket_number}")
    other = await enqueue(db_session, customer.id, key="support.ticket_replied", channel="PUSH")
    assert (await row(db_session, other.notification_id)).suppress_reason == "NO_APPROVED_TEMPLATE"


async def test_template_content_is_frozen_in_the_database(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    t = live_template(finance, boss)
    draft = create_template(finance, key="support.ticket_replied").json()
    for sql in (
        f"UPDATE notification_templates SET body='tampered' WHERE id='{t['id']}'",
        f"UPDATE notification_templates SET status='REJECTED' WHERE id='{t['id']}'",
        f"UPDATE notification_templates SET body='edited draft' WHERE id='{draft['id']}'",
        "DELETE FROM notification_templates",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()


# -------------------------------------------------------------- sending


async def test_happy_path_sends_once_with_minimal_stored_data(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id, variables={"ticket_number": "T-42"})
    assert (res.created, res.status) == (True, "PENDING")
    stats = await run_worker()
    assert stats["claimed"] == 1 and stats["sent"] == 1 and stats["errors"] == 0
    n = await row(db_session, res.notification_id)
    assert (n.status, n.attempts, n.provider, n.failure_code) == ("SENT", 1, "development", None)
    assert n.provider_ref and n.sent_at
    (msg,) = Prov.sent.values()
    assert msg["destination"] == customer.phone_number and msg["body"] == "Request T-42 received."
    # what we keep: the template version and the declared variables, never the text or the number
    assert n.variables == {"ticket_number": "T-42"}
    cols = {c.name for c in Notification.__table__.columns}
    assert not cols & {"body", "message", "text", "destination", "phone_number", "rendered"}
    assert "9" not in json.dumps(n.variables) or customer.phone_number not in json.dumps(n.variables)
    assert await attempts(db_session, n.id) == ["SENT"]
    again = await run_worker()
    assert again["claimed"] == 0 and len(Prov.send_calls) == 1


async def test_a_transient_failure_retries_later_with_backoff(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    Prov.behaviour = "transient"
    stats = await run_worker()
    assert stats["retry"] == 1
    n = await row(db_session, res.notification_id)
    assert (n.status, n.attempts, n.failure_code) == ("PENDING", 1, "PROVIDER_UNAVAILABLE")
    assert n.next_attempt_at > utcnow() + timedelta(seconds=30)
    Prov.behaviour = "ok"
    assert (await run_worker())["claimed"] == 0  # not due yet: no hammering
    forward(monkeypatch, minutes=2)
    stats = await run_worker()
    assert stats["sent"] == 1
    n = await row(db_session, res.notification_id)
    assert (n.status, n.attempts, n.failure_code) == ("SENT", 2, None)
    assert await attempts(db_session, n.id) == ["TRANSIENT_FAILURE", "SENT"]
    assert len(Prov.sent) == 1


async def test_retries_run_out_then_the_message_is_dead_lettered_and_can_be_requeued(monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "notification_max_attempts", 3)
    finance, boss, support, agent = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    nid = res.notification_id
    Prov.behaviour = "transient"
    await run_worker()
    n = await row(db_session, res.notification_id)
    # advance the clock enough for every retry to be due
    for _ in range(4):
        if n.status == "DEAD":
            break
        forward(monkeypatch, hours=3)
        await run_worker()
        n = await row(db_session, res.notification_id)
    assert (n.status, n.attempts, n.failure_code) == ("DEAD", 3, "RETRIES_EXHAUSTED")
    assert n.dead_at is not None
    assert await attempts(db_session, nid) == ["TRANSIENT_FAILURE"] * 3
    assert "NOTIFICATION_DEAD_LETTERED" in await audit(db_session)
    assert (await run_worker())["claimed"] == 0  # dead means no more automatic tries

    dead = client.get(f"{BASE}?status=DEAD", headers=support).json()
    assert [d["id"] for d in dead] == [str(nid)]
    assert client.post(f"{BASE}/{nid}/requeue", headers=support, json={"reason": "provider was down all day"}).status_code == 403
    assert client.post(f"{BASE}/{nid}/requeue", headers=finance, json={"reason": "short"}).status_code == 422
    Prov.behaviour = "ok"
    ok = client.post(f"{BASE}/{nid}/requeue", headers=finance, json={"reason": "provider was down all day"})
    assert ok.status_code == 200 and ok.json()["status"] == "PENDING" and ok.json()["attempts"] == 0
    assert client.post(f"{BASE}/{nid}/requeue", headers=finance, json={"reason": "again for no reason"}).status_code == 409
    assert (await run_worker())["sent"] == 1
    assert (await row(db_session, nid)).status == "SENT"
    assert "REQUEUED" in await attempts(db_session, nid)
    assert "NOTIFICATION_REQUEUED" in await audit(db_session)
    detail = client.get(f"{BASE}/{nid}", headers=support).json()
    assert [a["outcome"] for a in detail["attempts_log"]][-2:] == ["REQUEUED", "SENT"]


async def test_a_permanent_failure_is_dead_lettered_at_once(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    Prov.behaviour = "permanent"
    stats = await run_worker()
    assert stats["dead"] == 1
    n = await row(db_session, res.notification_id)
    assert (n.status, n.attempts, n.failure_code) == ("DEAD", 1, "INVALID_DESTINATION")
    assert await attempts(db_session, n.id) == ["PERMANENT_FAILURE"]
    forward(monkeypatch, days=2)
    assert (await run_worker())["claimed"] == 0 and len(Prov.send_calls) == 1


async def test_one_customers_bad_number_does_not_block_others(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    bad, _h1 = await make_actor(monkeypatch, db_session)
    good, _h2 = await make_actor(monkeypatch, db_session)
    Prov.behaviour = "permanent_for"
    Prov.bad_destinations = {bad.phone_number}
    a = await enqueue(db_session, bad.id)
    b = await enqueue(db_session, good.id)
    stats = await run_worker()
    assert (stats["dead"], stats["sent"]) == (1, 1)
    assert (await row(db_session, a.notification_id)).status == "DEAD"
    assert (await row(db_session, b.notification_id)).status == "SENT"


async def test_a_timeout_after_the_provider_accepted_never_double_sends(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    Prov.behaviour = "timeout_after"
    await run_worker()
    assert (await row(db_session, res.notification_id)).status == "PENDING"
    assert len(Prov.sent) == 1  # it did go out once
    Prov.behaviour = "ok"
    forward(monkeypatch, minutes=2)
    await run_worker()
    n = await row(db_session, res.notification_id)
    assert n.status == "SENT" and n.provider_ref == next(iter(Prov.sent.values()))["provider_ref"]
    assert len(Prov.sent) == 1 and len(Prov.send_calls) == 2
    assert len(set(Prov.send_calls)) == 1  # the same idempotency key both times


async def test_several_workers_at_once_send_each_message_once(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    users = [(await make_actor(monkeypatch, db_session))[0] for _ in range(4)]
    for u in users:
        await enqueue(db_session, u.id)
    results = await asyncio.gather(*(run_worker() for _ in range(3)))
    assert sum(r["claimed"] for r in results) == 4
    assert sum(r["sent"] for r in results) == 4
    assert len(Prov.send_calls) == 4 and len(set(Prov.send_calls)) == 4
    assert all(r["errors"] == 0 for r in results)


async def test_a_crashed_sender_is_retried_after_the_lease_and_dead_lettered_at_the_limit(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    # simulate a worker that claimed it and then died
    await db_session.execute(update(Notification).where(Notification.id == res.notification_id).values(
        status="SENDING", attempts=1, locked_at=utcnow() - timedelta(minutes=30)))
    await db_session.commit()
    await run_worker()
    n = await row(db_session, res.notification_id)
    assert (n.status, n.attempts) == ("SENT", 2)
    assert (await attempts(db_session, n.id))[0] == "LEASE_EXPIRED"
    # a fresh claim is left alone
    res2 = await enqueue(db_session, customer.id, dedupe="other")
    await db_session.execute(update(Notification).where(Notification.id == res2.notification_id).values(
        status="SENDING", attempts=1, locked_at=utcnow()))
    await db_session.commit()
    assert (await run_worker())["claimed"] == 0
    # one that already used every attempt dies instead of retrying
    res3 = await enqueue(db_session, customer.id, dedupe="third")
    await db_session.execute(update(Notification).where(Notification.id == res3.notification_id).values(
        status="SENDING", attempts=5, locked_at=utcnow() - timedelta(minutes=30)))
    await db_session.commit()
    await run_worker()
    n3 = await row(db_session, res3.notification_id)
    assert (n3.status, n3.failure_code) == ("DEAD", "LEASE_EXPIRED")


# ------------------------------------------------------ duplicate protection


async def test_the_same_dedupe_key_creates_one_notification(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    first = await enqueue(db_session, customer.id, dedupe="ticket:1:received")
    second = await enqueue(db_session, customer.id, dedupe="ticket:1:received")
    assert (first.created, second.created) == (True, False)
    assert first.notification_id == second.notification_id
    await run_worker()
    third = await enqueue(db_session, customer.id, dedupe="ticket:1:received")
    assert third.created is False and third.status == "SENT"
    assert len(Prov.sent) == 1
    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 1


async def test_concurrent_enqueues_with_one_key_make_one_row(monkeypatch, db_session):
    from app.db.session import AsyncSessionLocal

    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)

    async def one():
        async with AsyncSessionLocal() as s:
            r = await build_notification_service(s).enqueue(
                user_id=customer.id, template_key="support.ticket_received", channel="SMS",
                variables={"ticket_number": "T"}, dedupe_key="same-key")
            await s.commit()
            return r.created

    created = await asyncio.gather(*(one() for _ in range(6)))
    assert created.count(True) == 1
    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 1


async def test_money_and_collections_messages_must_carry_a_dedupe_key(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    customer, _h = await make_actor(monkeypatch, db_session)
    from app.domain.notifications import NotificationError

    for key in ("txn.payment_received", "collections.dpd_1.sms"):
        with pytest.raises(NotificationError):
            await build_notification_service(db_session).enqueue(
                user_id=customer.id, template_key=key, channel="SMS", variables={})
    await db_session.rollback()
    # service messages (support replies) may repeat on purpose
    live_template(finance, boss)
    a = await enqueue(db_session, customer.id)
    b = await enqueue(db_session, customer.id)
    assert a.notification_id != b.notification_id


async def test_the_database_refuses_a_duplicate_dedupe_key(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    await enqueue(db_session, customer.id, dedupe="k")
    with pytest.raises(DBAPIError):
        await db_session.execute(text(
            "INSERT INTO notifications (id, user_id, template_key, template_version, channel, category, variables, "
            "dedupe_key, status, attempts, max_attempts) SELECT gen_random_uuid(), user_id, template_key, "
            "template_version, channel, category, variables, dedupe_key, status, 0, 5 FROM notifications"))
    await db_session.rollback()


# ------------------------------------------------- preferences / eligibility


async def test_service_messages_respect_an_opt_out_even_after_queueing(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, h = await make_actor(monkeypatch, db_session)
    queued = await enqueue(db_session, customer.id)  # on by default
    put = client.put(f"{CUSTOMER}/preferences", headers=h, json={"category": "SERVICE", "channel": "SMS", "enabled": False})
    assert put.status_code == 200
    stats = await run_worker()  # re-checked at send time
    assert stats["suppressed"] == 1 and Prov.send_calls == []
    n = await row(db_session, queued.notification_id)
    assert (n.status, n.suppress_reason) == ("SUPPRESSED", "OPTED_OUT")
    later = await enqueue(db_session, customer.id)
    assert (await row(db_session, later.notification_id)).suppress_reason == "OPTED_OUT"
    client.put(f"{CUSTOMER}/preferences", headers=h, json={"category": "SERVICE", "channel": "SMS", "enabled": True})
    again = await enqueue(db_session, customer.id)
    assert again.status == "PENDING"
    assert "NOTIFICATION_PREFERENCE_CHANGED" in await audit(db_session)


async def test_marketing_needs_an_opt_in(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss, key="marketing.new_offer", body="New offer for you", variables=())
    customer, h = await make_actor(monkeypatch, db_session)
    off = await enqueue(db_session, customer.id, key="marketing.new_offer", variables={})
    assert (await row(db_session, off.notification_id)).suppress_reason == "NOT_OPTED_IN"
    client.put(f"{CUSTOMER}/preferences", headers=h, json={"category": "MARKETING", "channel": "SMS", "enabled": True})
    on = await enqueue(db_session, customer.id, key="marketing.new_offer", variables={})
    assert on.status == "PENDING"
    await run_worker()
    assert len(Prov.sent) == 1


async def test_transactional_messages_cannot_be_switched_off(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss, key="txn.payment_received", body="Payment of {amount} received", variables=("amount",))
    customer, h = await make_actor(monkeypatch, db_session)
    refused = client.put(f"{CUSTOMER}/preferences", headers=h,
                         json={"category": "TRANSACTIONAL", "channel": "SMS", "enabled": False})
    assert refused.status_code == 409
    for cat in ("SERVICE", "COLLECTIONS", "MARKETING"):
        client.put(f"{CUSTOMER}/preferences", headers=h, json={"category": cat, "channel": "SMS", "enabled": False})
    res = await enqueue(db_session, customer.id, key="txn.payment_received", variables={"amount": "500.00"}, dedupe="pay:1")
    assert res.status == "PENDING"
    await run_worker()
    assert next(iter(Prov.sent.values()))["body"] == "Payment of 500.00 received"


async def test_preference_listing_shows_effective_defaults(monkeypatch, db_session):
    customer, h = await make_actor(monkeypatch, db_session)
    prefs = client.get(f"{CUSTOMER}/preferences", headers=h).json()
    assert len(prefs) == 9 and all(p["category"] != "TRANSACTIONAL" for p in prefs)
    by = {(p["category"], p["channel"]): p["enabled"] for p in prefs}
    assert by[("SERVICE", "SMS")] is True and by[("COLLECTIONS", "SMS")] is True and by[("MARKETING", "SMS")] is False
    bad = client.put(f"{CUSTOMER}/preferences", headers=h, json={"category": "SERVICE", "channel": "SMS"})
    assert bad.status_code == 422
    assert client.get(f"{CUSTOMER}/preferences").status_code in (401, 403)


async def test_no_destination_and_inactive_users_are_not_messaged(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    live_template(finance, boss, channel="EMAIL", subject="Request received")
    customer, _h = await make_actor(monkeypatch, db_session)
    email = await enqueue(db_session, customer.id, channel="EMAIL")
    assert (await row(db_session, email.notification_id)).suppress_reason == "NO_DESTINATION"
    await db_session.execute(update(User).where(User.id == customer.id).values(status="blocked"))
    await db_session.commit()
    sms = await enqueue(db_session, customer.id)
    assert (await row(db_session, sms.notification_id)).suppress_reason == "USER_NOT_ACTIVE"
    await run_worker()
    assert Prov.send_calls == []


async def test_bad_variables_suppress_instead_of_sending_a_broken_message(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    for variables in ({}, {"ticket_number": "T", "salary": "9999"}, {"ticket_number": "two\nlines"}):
        res = await enqueue(db_session, customer.id, variables=variables)
        n = await row(db_session, res.notification_id)
        assert (n.status, n.suppress_reason, n.variables) == ("SUPPRESSED", "BAD_VARIABLES", {})
    await run_worker()
    assert Prov.send_calls == []


# ------------------------------------------------------------- receipts


async def test_delivery_receipts_update_status_once(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    await run_worker()
    ref = (await row(db_session, res.notification_id)).provider_ref
    first = receipt(ref, "DELIVERED", event_id="e1")
    assert first.status_code == 200 and first.json()["outcome"] == "DELIVERED"
    assert receipt(ref, "DELIVERED", event_id="e1").json()["outcome"] == "DUPLICATE"
    n = await row(db_session, res.notification_id)
    assert n.status == "DELIVERED" and n.delivered_at is not None
    late = receipt(ref, "FAILED", event_id="e2")
    assert late.json()["outcome"] == "IGNORED"  # the first word stands
    assert (await row(db_session, res.notification_id)).status == "DELIVERED"
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE notifications SET status='SENT'"))
    await db_session.rollback()


async def test_a_failed_delivery_receipt_is_recorded(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    await run_worker()
    ref = (await row(db_session, res.notification_id)).provider_ref
    assert receipt(ref, "FAILED").json()["outcome"] == "DELIVERY_FAILED"
    n = await row(db_session, res.notification_id)
    assert (n.status, n.failure_code) == ("DELIVERY_FAILED", "DELIVERY_FAILED")


async def test_receipt_security_and_unknown_references(monkeypatch, db_session):
    assert receipt("whatever", "DELIVERED", secret=None).status_code == 401
    assert receipt("whatever", "DELIVERED", secret="wrong").status_code == 401
    assert receipt("never-sent", "DELIVERED").json()["outcome"] == "UNKNOWN_REFERENCE"
    body = b"not json"
    headers = {**sign_webhook(SECRET, body), "Content-Type": "application/json"}
    assert client.post("/api/v1/webhooks/notification/development", content=body, headers=headers).status_code == 400
    odd = json.dumps({"event_id": "x", "provider_ref": "r", "status": "WEIRD"}).encode()
    headers = {**sign_webhook(SECRET, odd), "Content-Type": "application/json"}
    assert client.post("/api/v1/webhooks/notification/development", content=odd, headers=headers).status_code == 400
    assert client.post("/api/v1/webhooks/notification/otherprovider", content=odd, headers=headers).status_code == 400
    monkeypatch.setattr(get_settings(), "notification_webhook_secret", None)
    assert receipt("x", "DELIVERED").status_code == 401  # no secret configured: everything is refused


# ------------------------------------------------------------- customers


async def test_customers_see_only_their_own_and_only_minimal_fields(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    mine, mine_h = await make_actor(monkeypatch, db_session)
    other, other_h = await make_actor(monkeypatch, db_session)
    await enqueue(db_session, mine.id, variables={"ticket_number": "SECRET-REF"})
    await run_worker()
    got = client.get(CUSTOMER, headers=mine_h)
    assert got.status_code == 200 and len(got.json()) == 1
    assert set(got.json()[0]) == {"id", "template_key", "channel", "category", "status", "created_at", "sent_at"}
    assert "SECRET-REF" not in got.text and mine.phone_number not in got.text
    assert client.get(CUSTOMER, headers=other_h).json() == []
    assert client.get(CUSTOMER).status_code in (401, 403)


async def test_admin_access_by_role(monkeypatch, db_session):
    finance, boss, support, agent = await staff(monkeypatch, db_session)
    _, auditor = await make_actor(monkeypatch, db_session, role="AUDITOR")
    customer, customer_h = await make_actor(monkeypatch, db_session)
    live_template(finance, boss)
    res = await enqueue(db_session, customer.id)
    for who in (finance, boss, support, auditor):
        assert client.get(BASE, headers=who).status_code == 200
        assert client.get(f"{BASE}/{res.notification_id}", headers=who).status_code == 200
        assert client.get(f"{BASE}/summary", headers=who).status_code == 200
    assert client.get(BASE, headers=agent).status_code == 403
    assert client.get(BASE, headers=customer_h).status_code == 403
    assert client.post(f"{BASE}/templates", headers=auditor, json={"template_key": "support.x", "channel": "SMS",
                       "body": "x", "allowed_variables": []}).status_code == 403
    assert client.get(f"{BASE}/00000000-0000-0000-0000-000000000000", headers=support).status_code == 404
    counts = {c["status"]: c["count"] for c in client.get(f"{BASE}/summary", headers=support).json()}
    assert counts == {"PENDING": 1}
    assert client.get(f"{BASE}?status=BOGUS", headers=support).status_code == 422
    assert len(client.get(f"{BASE}?channel=SMS&template_key=support.ticket_received", headers=support).json()) == 1


async def test_notifications_cannot_be_deleted_or_redirected(monkeypatch, db_session):
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss)
    customer, _h = await make_actor(monkeypatch, db_session)
    res = await enqueue(db_session, customer.id)
    await run_worker()
    for sql in (
        "DELETE FROM notifications",
        "UPDATE notifications SET user_id = gen_random_uuid()",
        "UPDATE notifications SET variables = '{}'::jsonb",
        "UPDATE notifications SET channel = 'EMAIL'",
        "UPDATE notification_attempts SET outcome = 'SENT'",
        "DELETE FROM notification_attempts",
        "UPDATE notifications SET status='SUPPRESSED'",  # needs a reason
        "UPDATE notifications SET status='DEAD'",  # needs a dead_at
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()
    assert (await row(db_session, res.notification_id)).status == "SENT"


# ------------------------------------------------- collections hand-off (2.15)


async def test_collection_reminders_become_notifications_exactly_once(world, monkeypatch, db_session):
    from tests.api.test_collections_api import day, overdue_loan, sync

    monkeypatch.setattr(get_settings(), "collections_reminders_enabled", True)
    finance, boss, *_ = await staff(monkeypatch, db_session)
    live_template(finance, boss, key="collections.dpd_1.sms", body="Rs {overdue_total} is overdue by {dpd} day.",
                  variables=("dpd", "overdue_total"))
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 1))
    from app.services.collections_factory import build_collection_service
    from tests.api.test_collections_api import case_of

    case = await case_of(db_session)
    made = await build_collection_service(db_session).schedule_reminders(case.id)
    await db_session.commit()
    assert made == 2  # SMS + PUSH requests

    stats = await run_worker()
    assert stats["intake"] == 2
    db_session.expire_all()
    rows = list((await db_session.execute(select(Notification).order_by(Notification.channel))).scalars())
    by = {n.channel: n for n in rows}
    # PUSH has no approved template and no destination yet: recorded, suppressed, not sent
    assert by["PUSH"].status == "SUPPRESSED" and by["PUSH"].suppress_reason == "NO_APPROVED_TEMPLATE"
    assert by["SMS"].status == "SENT" and by["SMS"].user_id == r.customer_id
    (msg,) = Prov.sent.values()
    assert msg["body"].startswith("Rs ") and "is overdue by 1 day." in msg["body"]
    again = await run_worker()
    assert again["intake"] == 0 and again["claimed"] == 0 and len(Prov.send_calls) == 1
    assert by["SMS"].source_type == "collection_event" and by["SMS"].dedupe_key.startswith("collection_event:")
