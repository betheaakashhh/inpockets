"""2.15 collections on real Postgres with the development providers."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.domain.repayment import utcnow
from app.main import app
from app.models.admin_user import AdminUser
from app.models.audit_log import AuditLog
from app.models.collection import CollectionCase, CollectionEvent
from app.services.collections_factory import build_collection_service
from app.workers.collections import run_once as run_worker
from tests.api.test_disbursement_api import ready  # noqa: F401
from tests.api.test_loan_offer_api import world  # noqa: F401
from tests.api.test_repayment_api import (  # noqa: F401
    active_loan,
    count,
    disbursed,
    env,
    installments,
    make_actor,
    pay,
    settle,
    started,
)

client = TestClient(app)
D = Decimal
BASE = "/api/v1/admin/collections"


async def overdue_loan(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)  # two installments
    rows = await installments(db_session, r.schedule_id)
    r.rows = rows
    r.due1, r.due2 = rows[0].due_date, rows[1].due_date
    return r


async def sync(db_session, r, today):
    res = await build_collection_service(db_session).sync_schedule(r.schedule_id, today=today)
    await db_session.commit()
    return res


async def cases(db_session):
    db_session.expire_all()
    return list((await db_session.execute(select(CollectionCase).order_by(CollectionCase.opened_at))).scalars())


async def case_of(db_session):
    (c,) = await cases(db_session)
    return c


async def events(db_session, *types):
    db_session.expire_all()
    stmt = select(CollectionEvent).order_by(CollectionEvent.created_at, CollectionEvent.id)
    if types:
        stmt = stmt.where(CollectionEvent.event_type.in_(types))
    return list((await db_session.execute(stmt)).scalars())


async def audit(db_session):
    return [a for (a,) in await db_session.execute(select(AuditLog.action))]


def day(r, n):
    return r.due1 + timedelta(days=n)


# ----------------------------------------------------------- DPD sync


async def test_no_case_on_or_before_the_due_date_then_dpd_1_the_day_after(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    for n in (-5, 0):
        assert (await sync(db_session, r, day(r, n))).action == "none"
    assert await cases(db_session) == []
    assert (await sync(db_session, r, day(r, 1))).action == "opened"
    c = await case_of(db_session)
    assert (c.status, c.dpd, c.dpd_bucket, c.escalation_level) == ("OPEN", 1, "1-7", 0)
    assert c.user_id == r.customer_id and str(c.loan_offer_id) == r.offer_id
    assert c.oldest_installment_id == r.rows[0].id
    assert c.overdue_principal == r.rows[0].principal_due and c.overdue_fees == 0


async def test_dpd_and_bucket_follow_the_calendar(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 1))
    seen = []
    for n in (7, 8, 30, 31):
        await sync(db_session, r, day(r, n))
        c = await case_of(db_session)
        seen.append((c.dpd, c.dpd_bucket))
    assert seen == [(7, "1-7"), (8, "8-30"), (30, "8-30"), (31, "31-60")]
    changes = [(e.payload["from"], e.payload["to"]) for e in await events(db_session, "BUCKET_CHANGED")]
    assert changes == [("1-7", "8-30"), ("8-30", "31-60")]  # only real changes are recorded


async def test_syncing_again_changes_nothing_and_never_duplicates(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    for _ in range(3):
        await sync(db_session, r, day(r, 5))
    assert len(await cases(db_session)) == 1
    assert len(await events(db_session, "CASE_OPENED")) == 1


async def test_concurrent_syncs_open_exactly_one_case(world, db_session, monkeypatch):
    from app.db.session import AsyncSessionLocal

    r = await overdue_loan(world, db_session, monkeypatch)

    async def one():
        async with AsyncSessionLocal() as s:
            res = await build_collection_service(s).sync_schedule(r.schedule_id, today=day(r, 3))
            await s.commit()
            return res.action

    actions = await asyncio.gather(*(one() for _ in range(5)))
    assert actions.count("opened") == 1
    assert len(await cases(db_session)) == 1 and len(await events(db_session, "CASE_OPENED")) == 1


async def test_a_partial_payment_reduces_the_overdue_amount_and_full_payment_closes_the_case(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 2))
    first = r.rows[0]
    total = first.principal_due + first.interest_due
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "SUCCESS", amount="1000.00")
    await sync(db_session, r, day(r, 2))
    c = await case_of(db_session)
    assert c.status == "OPEN" and c.overdue_principal + c.overdue_interest == total - D("1000.00")
    pid, ref = await started(world, r, str(total - D("1000.00")), db_session)
    settle(ref, "SUCCESS", amount=str(total - D("1000.00")))
    assert (await sync(db_session, r, day(r, 2))).action == "closed"
    c = await case_of(db_session)
    assert (c.status, c.close_reason) == ("CLOSED", "CURED") and c.closed_at
    assert (await events(db_session, "CASE_CLOSED"))[0].payload["reason"] == "CURED"
    # still not overdue: nothing reopens it
    assert (await sync(db_session, r, day(r, 3))).action == "none"
    assert len(await cases(db_session)) == 1


async def test_dpd_moves_to_the_next_installment_when_the_oldest_is_paid(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    today = r.due2 + timedelta(days=4)
    await sync(db_session, r, today)
    assert (await case_of(db_session)).oldest_installment_id == r.rows[0].id
    first = r.rows[0]
    amount = str(first.principal_due + first.interest_due + first.fee_due)
    pid, ref = await started(world, r, amount, db_session)
    settle(ref, "SUCCESS", amount=amount)
    await sync(db_session, r, today)
    c = await case_of(db_session)
    assert (c.status, c.dpd, c.oldest_installment_id) == ("OPEN", 4, r.rows[1].id)


async def test_a_new_default_after_a_closed_case_opens_a_new_case(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 1))
    first = r.rows[0]
    amount = str(first.principal_due + first.interest_due)
    pid, ref = await started(world, r, amount, db_session)
    settle(ref, "SUCCESS", amount=amount)
    assert (await sync(db_session, r, day(r, 1))).action == "closed"
    assert (await sync(db_session, r, r.due2 + timedelta(days=2))).action == "opened"
    got = await cases(db_session)
    assert [c.status for c in got] == ["CLOSED", "OPEN"]


# ------------------------------------------------------------ reminders


async def test_reminders_are_off_until_switched_on(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 1))
    svc = build_collection_service(db_session)
    assert await svc.reminder_candidates() == []
    assert await svc.schedule_reminders((await case_of(db_session)).id) == 0
    assert await events(db_session, "REMINDER_SCHEDULED") == []


async def test_reminders_are_created_once_per_milestone_and_channel(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "collections_reminders_enabled", True)
    r = await overdue_loan(world, db_session, monkeypatch)

    async def remind(n):
        await sync(db_session, r, day(r, n))
        made = await build_collection_service(db_session).schedule_reminders((await case_of(db_session)).id)
        await db_session.commit()
        return made

    assert await remind(1) == 2  # SMS + PUSH
    assert await remind(1) == 0 and await remind(2) == 0  # repeat / nothing new
    assert await remind(3) == 1  # SMS only
    assert await remind(3) == 0
    got = await events(db_session, "REMINDER_SCHEDULED")
    assert sorted((e.channel, e.payload["milestone"]) for e in got) == [
        ("PUSH", 1), ("SMS", 1), ("SMS", 3)]
    assert all(e.template_key.startswith("collections.dpd_") and e.dedupe_key for e in got)
    assert (await case_of(db_session)).last_reminder_at is not None


async def test_after_downtime_only_the_latest_milestone_is_sent_not_a_burst(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "collections_reminders_enabled", True)
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 10))
    assert await build_collection_service(db_session).schedule_reminders((await case_of(db_session)).id) == 2
    await db_session.commit()
    assert {e.payload["milestone"] for e in await events(db_session, "REMINDER_SCHEDULED")} == {7}


async def test_concurrent_reminder_runs_create_each_reminder_once(world, db_session, monkeypatch):
    from app.db.session import AsyncSessionLocal

    monkeypatch.setattr(get_settings(), "collections_reminders_enabled", True)
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 1))
    cid = (await case_of(db_session)).id

    async def one():
        async with AsyncSessionLocal() as s:
            n = await build_collection_service(s).schedule_reminders(cid)
            await s.commit()
            return n

    assert sum(await asyncio.gather(*(one() for _ in range(5)))) == 2
    assert len(await events(db_session, "REMINDER_SCHEDULED")) == 2


async def test_the_database_itself_refuses_a_duplicate_reminder(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "collections_reminders_enabled", True)
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 1))
    cid = (await case_of(db_session)).id
    await build_collection_service(db_session).schedule_reminders(cid)
    await db_session.commit()
    with pytest.raises(DBAPIError):
        await db_session.execute(text(
            "INSERT INTO collection_events (id, case_id, event_type, actor_type, dedupe_key, channel, template_key) "
            "SELECT gen_random_uuid(), case_id, event_type, actor_type, dedupe_key, channel, template_key "
            "FROM collection_events WHERE event_type='REMINDER_SCHEDULED' LIMIT 1"))
    await db_session.rollback()


# ----------------------------------------------------------- escalation


async def test_escalation_follows_the_thresholds_and_only_goes_up(world, db_session, monkeypatch):
    r = await overdue_loan(world, db_session, monkeypatch)

    async def esc(n):
        await sync(db_session, r, day(r, n))
        level = await build_collection_service(db_session).escalate_case((await case_of(db_session)).id)
        await db_session.commit()
        return level

    assert await esc(29) is None
    assert await esc(30) == 1
    c = await case_of(db_session)
    assert (c.status, c.escalation_level, c.next_action) == ("ESCALATED", 1, "ESCALATION_REVIEW")
    assert await esc(30) is None and await esc(45) is None  # nothing new
    assert await esc(61) == 2 and await esc(95) == 3 and await esc(400) is None
    levels = [e.payload["to_level"] for e in await events(db_session, "ESCALATED")]
    assert levels == [1, 2, 3]
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE collection_cases SET escalation_level = 0, status='OPEN'"))
    await db_session.rollback()


async def test_escalation_can_be_switched_off(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "collections_escalation_enabled", False)
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, 100))
    svc = build_collection_service(db_session)
    assert await svc.escalation_candidates() == []
    assert await svc.escalate_case((await case_of(db_session)).id) is None


# --------------------------------------------------------------- worker


async def test_worker_pass_is_complete_bounded_and_idempotent(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "collections_reminders_enabled", True)
    r = await overdue_loan(world, db_session, monkeypatch)
    stats = await run_worker(today=day(r, 35))
    assert stats["opened"] == 1 and stats["errors"] == 0
    assert stats["reminders"] == 2 and stats["escalated"] == 1  # milestone 30: SMS + EMAIL
    c = await case_of(db_session)
    assert (c.status, c.dpd, c.escalation_level) == ("ESCALATED", 35, 1)
    again = await run_worker(today=day(r, 35))
    assert again == {"opened": 0, "updated": 0, "closed": 0, "reminders": 0, "escalated": 0, "errors": 0}
    later = await run_worker(today=day(r, 36))
    assert later["updated"] == 1 and later["reminders"] == 0


async def test_worker_respects_the_batch_size(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "collections_batch_size", 1)
    r = await overdue_loan(world, db_session, monkeypatch)
    svc = build_collection_service(db_session)
    assert len(await svc.sync_candidates(today=day(r, 3))) == 1
    assert await svc.sync_candidates(limit=5, today=day(r, -3)) == []


# ------------------------------------------------------------ admin API


async def admins(monkeypatch, db_session):
    agent, agent_h = await make_actor(monkeypatch, db_session, role="COLLECTIONS_AGENT")
    agent2, agent2_h = await make_actor(monkeypatch, db_session, role="COLLECTIONS_AGENT")
    boss, boss_h = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    _, auditor_h = await make_actor(monkeypatch, db_session, role="AUDITOR")
    _, support_h = await make_actor(monkeypatch, db_session, role="CUSTOMER_SUPPORT")

    async def admin_id(user):
        return (await db_session.execute(select(AdminUser.id).where(AdminUser.user_id == user.id))).scalar_one()

    return {
        "agent": agent_h, "agent2": agent2_h, "boss": boss_h, "auditor": auditor_h, "support": support_h,
        "agent_id": str(await admin_id(agent)), "agent2_id": str(await admin_id(agent2)),
        "boss_id": str(await admin_id(boss)),
    }


async def open_case(world, db_session, monkeypatch, n=2):
    r = await overdue_loan(world, db_session, monkeypatch)
    await sync(db_session, r, day(r, n))
    r.case_id = str((await case_of(db_session)).id)
    return r


def post(h, case_id, path, **body):
    return client.post(f"{BASE}/cases/{case_id}/{path}", json=body, headers=h)


async def test_reading_cases_and_permissions(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    a = await admins(monkeypatch, db_session)
    for who in ("agent", "boss", "auditor"):
        got = client.get(f"{BASE}/cases", headers=a[who])
        assert got.status_code == 200 and len(got.json()) == 1
        assert client.get(f"{BASE}/summary", headers=a[who]).status_code == 200
    assert client.get(f"{BASE}/cases", headers=a["support"]).status_code == 403
    assert client.get(f"{BASE}/cases", headers=world.customer_headers).status_code == 403
    assert client.get(f"{BASE}/cases").status_code in (401, 403)
    one = client.get(f"{BASE}/cases/{r.case_id}", headers=a["agent"]).json()
    assert one["id"] == r.case_id and one["events"][0]["event_type"] == "CASE_OPENED"
    assert client.get(f"{BASE}/cases/00000000-0000-0000-0000-000000000000", headers=a["agent"]).status_code == 404
    summary = client.get(f"{BASE}/summary", headers=a["boss"]).json()
    assert summary["total_cases"] == 1 and summary["rows"][0]["bucket"] == "1-7"
    assert D(summary["rows"][0]["overdue_total"]) > 0
    # an auditor reads but cannot work a case
    assert post(a["auditor"], r.case_id, "assign").status_code == 403
    assert post(a["auditor"], r.case_id, "notes", note="trying to write").status_code == 403


async def test_list_filters(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    a = await admins(monkeypatch, db_session)
    h = a["agent"]
    assert len(client.get(f"{BASE}/cases?unassigned=true", headers=h).json()) == 1
    assert client.get(f"{BASE}/cases?mine=true", headers=h).json() == []
    assert client.post(f"{BASE}/cases/{r.case_id}/assign", json={}, headers=h).status_code == 200
    assert len(client.get(f"{BASE}/cases?mine=true", headers=h).json()) == 1
    assert client.get(f"{BASE}/cases?unassigned=true", headers=h).json() == []
    assert len(client.get(f"{BASE}/cases?bucket=1-7&status=OPEN&min_dpd=1", headers=h).json()) == 1
    assert client.get(f"{BASE}/cases?bucket=8-30", headers=h).json() == []
    assert client.get(f"{BASE}/cases?bucket=bogus", headers=h).status_code == 400
    assert client.get(f"{BASE}/cases?status=BOGUS", headers=h).status_code == 422
    assert client.get(f"{BASE}/cases?min_dpd=5", headers=h).json() == []


async def test_agent_workflow_assignment_notes_contact_next_action(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    a = await admins(monkeypatch, db_session)
    # an agent cannot work a case that is not theirs
    assert post(a["agent"], r.case_id, "notes", note="not mine yet").status_code == 403
    mine = post(a["agent"], r.case_id, "assign")
    assert mine.status_code == 200 and mine.json()["assigned_to_admin_user_id"] == a["agent_id"]
    assert mine.json()["status"] == "OPEN"
    assert post(a["agent"], r.case_id, "assign").status_code == 200  # idempotent
    assert len(await events(db_session, "ASSIGNED")) == 1
    # another agent cannot take or work it
    assert post(a["agent2"], r.case_id, "assign").status_code == 409
    assert post(a["agent2"], r.case_id, "notes", note="not mine either").status_code == 403
    # agents cannot hand it to someone else; a manager can
    assert post(a["agent"], r.case_id, "assign", assignee_admin_user_id=a["agent2_id"]).status_code == 403

    noted = post(a["agent"], r.case_id, "notes", note="Customer said salary arrives on the 5th")
    assert noted.status_code == 200 and noted.json()["status"] == "IN_PROGRESS"
    assert post(a["agent"], r.case_id, "notes", note="x").status_code == 422
    contact = post(a["agent"], r.case_id, "contact-attempts", channel="CALL", outcome="NO_ANSWER")
    assert contact.status_code == 200 and contact.json()["last_contact_at"]
    assert post(a["agent"], r.case_id, "contact-attempts", channel="CALL", outcome="SHOUTED").status_code == 422
    due = (utcnow() + timedelta(days=1)).isoformat()
    nxt = post(a["agent"], r.case_id, "next-action", action="CALL", due_at=due, note="try the evening")
    assert nxt.status_code == 200 and nxt.json()["next_action"] == "CALL"
    past = (utcnow() - timedelta(hours=1)).isoformat()
    assert post(a["agent"], r.case_id, "next-action", action="CALL", due_at=past).status_code == 400
    assert post(a["agent"], r.case_id, "next-action", action="CALL", due_at="2030-01-01T10:00:00").status_code == 400
    far = (utcnow() + timedelta(days=200)).isoformat()
    assert post(a["agent"], r.case_id, "next-action", action="CALL", due_at=far).status_code == 400
    assert post(a["agent"], r.case_id, "next-action", action="PROMISE_TO_PAY", due_at=due).status_code == 422

    moved = post(a["boss"], r.case_id, "assign", assignee_admin_user_id=a["agent2_id"])
    assert moved.status_code == 200 and moved.json()["assigned_to_admin_user_id"] == a["agent2_id"]
    assert post(a["agent"], r.case_id, "notes", note="no longer mine").status_code == 403
    assert post(a["agent2"], r.case_id, "notes", note="taking over this one").status_code == 200
    # a manager cannot assign to someone who cannot take cases
    assert post(a["boss"], r.case_id, "assign", assignee_admin_user_id=str(uuid_zero())).status_code == 400

    history = client.get(f"{BASE}/cases/{r.case_id}", headers=a["boss"]).json()["events"]
    kinds = [e["event_type"] for e in history]
    assert kinds[0] == "CASE_OPENED"
    assert kinds.count("ASSIGNED") == 2 and kinds.count("NOTE_ADDED") == 2
    assert "CONTACT_ATTEMPT" in kinds and "NEXT_ACTION_SET" in kinds
    assert all(e["actor_type"] == "ADMIN" for e in history[1:])
    acts = await audit(db_session)
    for name in ("COLLECTION_CASE_ASSIGNED", "COLLECTION_NOTE_ADDED", "COLLECTION_CONTACT_LOGGED", "COLLECTION_NEXT_ACTION_SET"):
        assert name in acts


def uuid_zero():
    import uuid
    return uuid.UUID(int=0)


async def test_assigning_to_an_admin_without_collections_rights_is_refused(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    a = await admins(monkeypatch, db_session)
    _, _ = await make_actor(monkeypatch, db_session, role="UNDERWRITER")
    uw = (await db_session.execute(select(AdminUser.id).where(AdminUser.role == "UNDERWRITER"))).scalar_one()
    assert post(a["boss"], r.case_id, "assign", assignee_admin_user_id=str(uw)).status_code == 400


async def test_manual_escalation_needs_a_manager_and_a_reason(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    a = await admins(monkeypatch, db_session)
    assert post(a["agent"], r.case_id, "escalate", reason="customer is unreachable").status_code == 403
    assert post(a["boss"], r.case_id, "escalate", reason="short").status_code == 422
    ok = post(a["boss"], r.case_id, "escalate", reason="customer is unreachable for a week")
    assert ok.status_code == 200
    assert (ok.json()["status"], ok.json()["escalation_level"]) == ("ESCALATED", 1)
    for _ in range(2):
        assert post(a["boss"], r.case_id, "escalate", reason="still unreachable, going higher").status_code == 200
    assert post(a["boss"], r.case_id, "escalate", reason="already at the top level").status_code == 409
    assert "COLLECTION_CASE_ESCALATED_MANUALLY" in await audit(db_session)
    # the automatic pass never lowers it and adds nothing at low DPD
    await sync(db_session, r, day(r, 3))
    assert (await case_of(db_session)).escalation_level == 3


async def test_a_closed_case_cannot_be_worked(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch, n=1)
    a = await admins(monkeypatch, db_session)
    post(a["agent"], r.case_id, "assign")
    first = r.rows[0]
    amount = str(first.principal_due + first.interest_due)
    pid, ref = await started(world, r, amount, db_session)
    settle(ref, "SUCCESS", amount=amount)
    await sync(db_session, r, day(r, 1))
    assert (await case_of(db_session)).status == "CLOSED"
    assert post(a["agent"], r.case_id, "notes", note="too late to note").status_code == 409
    assert post(a["boss"], r.case_id, "assign", assignee_admin_user_id=a["agent2_id"]).status_code == 409
    assert post(a["boss"], r.case_id, "escalate", reason="closed so this must fail").status_code == 409
    assert client.get(f"{BASE}/summary", headers=a["boss"]).json()["total_cases"] == 0


async def test_there_is_no_promise_to_pay(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    a = await admins(monkeypatch, db_session)
    assert post(a["boss"], r.case_id, "promise-to-pay", amount="100").status_code in (404, 405)


# --------------------------------------------------------- database rules


async def test_history_is_append_only_and_cases_keep_their_loan(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch)
    for sql in (
        "UPDATE collection_events SET note='edited'",
        "DELETE FROM collection_events",
        "DELETE FROM collection_cases",
        "UPDATE collection_cases SET schedule_id = gen_random_uuid()",
        "UPDATE collection_cases SET user_id = gen_random_uuid()",
        "UPDATE collection_cases SET status='CLOSED'",  # closed needs a reason and time
        "UPDATE collection_cases SET status='ESCALATED'",  # escalated needs a level
        "UPDATE collection_cases SET dpd = 0",  # an open case is overdue
        "UPDATE collection_cases SET assigned_at = now()",  # assignment needs an assignee
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()


async def test_a_closed_case_is_final_and_one_live_case_per_schedule(world, db_session, monkeypatch):
    r = await open_case(world, db_session, monkeypatch, n=1)
    c = await case_of(db_session)
    cid = c.id
    with pytest.raises(DBAPIError):  # a second live case for the same loan
        await db_session.execute(text(
            "INSERT INTO collection_cases (id, user_id, loan_offer_id, schedule_id, oldest_installment_id, status, dpd, "
            "dpd_bucket, overdue_principal, overdue_interest, overdue_fees, escalation_level) "
            "SELECT gen_random_uuid(), user_id, loan_offer_id, schedule_id, oldest_installment_id, 'OPEN', 1, '1-7', 1, 0, 0, 0 "
            "FROM collection_cases"))
    await db_session.rollback()
    first = r.rows[0]
    amount = str(first.principal_due + first.interest_due)
    pid, ref = await started(world, r, amount, db_session)
    settle(ref, "SUCCESS", amount=amount)
    await sync(db_session, r, day(r, 1))
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE collection_cases SET dpd = 5 WHERE id = :i"), {"i": cid})
    await db_session.rollback()
