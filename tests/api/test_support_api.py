"""2.17 support tickets and grievances on real Postgres."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

import app.services.support as support_service
from app.core.config import get_settings
from app.main import app
from app.models.admin_user import AdminUser
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.support import SupportTicket, SupportTicketEvent
from tests.api.test_loan_offer_api import make_actor as _make_actor
from tests.api.test_loan_offer_api import world  # noqa: F401

client = TestClient(app)
ME = "/api/v1/support"
ADM = "/api/v1/admin/support"


@pytest.fixture(autouse=True)
def support_env(monkeypatch):
    s = get_settings()
    for name in ("rate_limit_sensitive_per_minute", "rate_limit_user_per_minute"):
        monkeypatch.setattr(s, name, 1000)


async def actor(monkeypatch, db_session, role=None):
    row, headers = await _make_actor(monkeypatch, db_session, role=role)
    admin_id = None
    if role:
        admin_id = (await db_session.execute(select(AdminUser.id).where(AdminUser.user_id == row.id))).scalar_one()
    return SimpleNamespace(id=row.id, phone=row.phone_number, admin_id=admin_id, h=headers)


def new_ticket(h, kind="ISSUE", category="REPAYMENT", subject="Payment not showing", message="I paid but it is not shown", **extra):
    return client.post(f"{ME}/tickets", headers=h, json={
        "kind": kind, "category": category, "subject": subject, "message": message, **extra})


async def audit(db_session):
    db_session.expire_all()
    return [a for (a,) in await db_session.execute(select(AuditLog.action))]


async def events(db_session, ticket_id):
    db_session.expire_all()
    return list((await db_session.execute(
        select(SupportTicketEvent).where(SupportTicketEvent.ticket_id == ticket_id)
        .order_by(SupportTicketEvent.created_at))).scalars())


def status_of(h, tid, status, note=None):
    body = {"status": status}
    if note is not None:
        body["note"] = note
    return client.post(f"{ADM}/tickets/{tid}/status", headers=h, json=body)


# ------------------------------------------------------- customer side


async def test_customer_creates_and_reads_own_ticket(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    res = new_ticket(c.h)
    assert res.status_code == 201, res.text
    t = res.json()
    assert t["ticket_number"].startswith("INP-") and t["status"] == "OPEN"
    assert [e["event_type"] for e in t["events"]] == ["TICKET_CREATED"]
    assert t["events"][0]["from"] == "YOU"
    assert client.get(f"{ME}/tickets", headers=c.h).json()[0]["id"] == t["id"]
    assert client.get(f"{ME}/tickets/{t['id']}", headers=c.h).status_code == 200
    # customer payload carries nothing staff-only
    assert not {"priority", "assigned_to_admin_user_id", "escalation_level", "sensitive", "sla_due_at"} & set(t)
    assert "SUPPORT_TICKET_CREATED" in await audit(db_session)


async def test_authentication_required():
    assert client.get(f"{ME}/tickets").status_code in (401, 403)
    assert client.post(f"{ME}/tickets", json={}).status_code in (401, 403)
    assert client.get(f"{ADM}/tickets").status_code in (401, 403)


async def test_customer_cannot_touch_someone_elses_ticket(monkeypatch, db_session):
    a, b = await actor(monkeypatch, db_session), await actor(monkeypatch, db_session)
    tid = new_ticket(a.h).json()["id"]
    assert client.get(f"{ME}/tickets/{tid}", headers=b.h).status_code == 404
    assert client.post(f"{ME}/tickets/{tid}/messages", headers=b.h, json={"message": "hi"}).status_code == 404
    assert client.get(f"{ME}/tickets", headers=b.h).json() == []


async def test_customer_is_not_an_admin(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    assert client.get(f"{ADM}/tickets", headers=c.h).status_code == 403
    assert client.get(f"{ADM}/tickets/{tid}", headers=c.h).status_code == 403


@pytest.mark.parametrize("payload", [
    {"kind": "ISSUE", "category": "KYC", "subject": "ab", "message": "x"},
    {"kind": "ISSUE", "category": "KYC", "subject": "Fine subject", "message": ""},
    {"kind": "ISSUE", "category": "KYC", "subject": "Fine subject", "message": "x" * 2001},
    {"kind": "NOPE", "category": "KYC", "subject": "Fine subject", "message": "x"},
    {"kind": "ISSUE", "category": "NOPE", "subject": "Fine subject", "message": "x"},
    {"kind": "ISSUE", "category": "KYC", "subject": "Fine subject", "message": "x", "status": "CLOSED"},
])
async def test_create_validation(monkeypatch, db_session, payload):
    c = await actor(monkeypatch, db_session)
    assert client.post(f"{ME}/tickets", headers=c.h, json=payload).status_code in (400, 422)


async def test_whitespace_only_message_is_rejected(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    assert new_ticket(c.h, message="    ").status_code == 400


async def test_max_open_tickets(monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "support_max_open_tickets_per_user", 2)
    c = await actor(monkeypatch, db_session)
    assert new_ticket(c.h).status_code == 201 and new_ticket(c.h).status_code == 201
    assert new_ticket(c.h).status_code == 409
    other = await actor(monkeypatch, db_session)
    assert new_ticket(other.h).status_code == 201  # per user


async def test_link_must_belong_to_the_customer(monkeypatch, db_session, world):  # noqa: F811
    c = await actor(monkeypatch, db_session)
    assert new_ticket(c.h, loan_application_id=str(uuid4())).status_code == 404
    assert new_ticket(c.h, loan_offer_id=str(uuid4())).status_code == 404


async def test_ticket_numbers_are_unique_and_increasing(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    nums = [new_ticket(c.h).json()["ticket_number"] for _ in range(3)]
    assert len(set(nums)) == 3 and nums == sorted(nums)


async def test_complaint_gets_a_deadline_question_does_not(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    q = new_ticket(c.h, kind="QUESTION").json()["id"]
    k = new_ticket(c.h, kind="COMPLAINT", category="CHARGES").json()["id"]
    db_session.expire_all()
    rows = {str(t.id): t for (t,) in await db_session.execute(select(SupportTicket))}
    assert rows[q].sla_due_at is None and rows[k].sla_due_at is not None


# ------------------------------------------------------- admin access


async def test_admin_role_access(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    sup = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    boss = await actor(monkeypatch, db_session, "SUPER_ADMIN")
    for role in ("COLLECTIONS_AGENT", "AUDITOR", "FINANCE"):
        other = await actor(monkeypatch, db_session, role)
        assert client.get(f"{ADM}/tickets", headers=other.h).status_code == 403, role
        assert client.get(f"{ADM}/tickets/{tid}", headers=other.h).status_code == 403, role
        assert client.get(f"{ADM}/summary", headers=other.h).status_code == 403, role
    for who in (sup, boss):
        assert client.get(f"{ADM}/tickets", headers=who.h).status_code == 200
        assert client.get(f"{ADM}/summary", headers=who.h).status_code == 200
        assert client.get(f"{ADM}/tickets/{tid}", headers=who.h).status_code == 200


async def test_admin_detail_masks_phone_and_shows_internal_notes(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    sup = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    assert client.post(f"{ADM}/tickets/{tid}/notes", headers=sup.h, json={"note": "checked the bank"}).status_code == 200
    d = client.get(f"{ADM}/tickets/{tid}", headers=sup.h).json()
    assert d["customer_phone_masked"].endswith(c.phone[-4:]) and c.phone not in str(d)
    assert "INTERNAL_NOTE" in [e["event_type"] for e in d["events"]]
    # the customer never sees the note or the assignment
    mine = client.get(f"{ME}/tickets/{tid}", headers=c.h).json()
    assert {e["event_type"] for e in mine["events"]} <= {"TICKET_CREATED", "CUSTOMER_MESSAGE", "AGENT_REPLY", "STATUS_CHANGED"}
    assert "checked the bank" not in str(mine)


async def test_reveal_contact_is_audited_and_permissioned(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    sup = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    res = client.post(f"{ADM}/tickets/{tid}/reveal-contact", headers=sup.h)
    assert res.status_code == 200 and res.json()["phone_number"] == c.phone
    assert "SUPPORT_CONTACT_REVEALED" in await audit(db_session)
    kinds = [e.event_type for e in await events(db_session, tid)]
    assert "CONTACT_REVEALED" in kinds
    # no leak of the number in any history text
    assert c.phone not in str([e.payload for e in await events(db_session, tid)])
    for role in ("COLLECTIONS_AGENT", "AUDITOR"):
        o = await actor(monkeypatch, db_session, role)
        assert client.post(f"{ADM}/tickets/{tid}/reveal-contact", headers=o.h).status_code == 403
    assert client.post(f"{ADM}/tickets/{tid}/reveal-contact", headers=c.h).status_code == 403


async def test_sensitive_tickets_hidden_from_ordinary_staff(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h, kind="COMPLAINT", category="FRAUD_OR_UNAUTHORISED").json()["id"]
    plain = new_ticket(c.h).json()["id"]
    sup = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    boss = await actor(monkeypatch, db_session, "SUPER_ADMIN")
    assert client.get(f"{ADM}/tickets/{tid}", headers=sup.h).status_code == 404
    for path, body in (("notes", {"note": "peek peek"}), ("replies", {"message": "hello"}),
                       ("status", {"status": "IN_PROGRESS"}), ("priority", {"priority": "LOW"}),
                       ("assign", {}), ("reveal-contact", None)):
        res = client.post(f"{ADM}/tickets/{tid}/{path}", headers=sup.h, json=body) if body is not None \
            else client.post(f"{ADM}/tickets/{tid}/{path}", headers=sup.h)
        assert res.status_code == 404, path
    assert {t["id"] for t in client.get(f"{ADM}/tickets", headers=sup.h).json()} == {plain}
    assert sum(r["count"] for r in client.get(f"{ADM}/summary", headers=sup.h).json()) == 1
    assert {t["id"] for t in client.get(f"{ADM}/tickets", headers=boss.h).json()} == {tid, plain}
    # the manager can open it, and that is audited
    assert client.get(f"{ADM}/tickets/{tid}", headers=boss.h).status_code == 200
    assert "SUPPORT_SENSITIVE_TICKET_VIEWED" in await audit(db_session)
    # sensitive tickets start at high priority
    assert client.get(f"{ADM}/tickets/{tid}", headers=boss.h).json()["priority"] == "HIGH"


async def test_viewing_an_ordinary_ticket_is_not_audited_as_sensitive(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    sup = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    client.get(f"{ADM}/tickets/{tid}", headers=sup.h)
    assert "SUPPORT_SENSITIVE_TICKET_VIEWED" not in await audit(db_session)


# ------------------------------------------------ ownership and workflow


async def test_first_worker_claims_and_others_are_blocked(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    b = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    boss = await actor(monkeypatch, db_session, "SUPER_ADMIN")
    first = client.post(f"{ADM}/tickets/{tid}/replies", headers=a.h, json={"message": "Looking into it"})
    assert first.status_code == 200 and first.json()["assigned_to_admin_user_id"] == str(a.admin_id)
    assert client.post(f"{ADM}/tickets/{tid}/replies", headers=b.h, json={"message": "me too"}).status_code == 403
    assert client.post(f"{ADM}/tickets/{tid}/notes", headers=b.h, json={"note": "sneaky"}).status_code == 403
    assert status_of(b.h, tid, "RESOLVED", "closing it now").status_code == 403
    # a manager can step in, and read-only access for the other agent stays open
    assert client.post(f"{ADM}/tickets/{tid}/notes", headers=boss.h, json={"note": "manager note"}).status_code == 200
    assert client.get(f"{ADM}/tickets/{tid}", headers=b.h).status_code == 200


async def test_assign_needs_manager_and_audits(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    boss = await actor(monkeypatch, db_session, "SUPER_ADMIN")
    res = client.post(f"{ADM}/tickets/{tid}/assign", headers=boss.h, json={"assignee_admin_user_id": str(a.admin_id)})
    assert res.status_code == 200 and res.json()["assigned_to_admin_user_id"] == str(a.admin_id)
    assert "SUPPORT_TICKET_ASSIGNED" in await audit(db_session)
    b = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    # an agent cannot hand work to someone else or take over another agent's ticket
    assert client.post(f"{ADM}/tickets/{tid}/assign", headers=b.h,
                       json={"assignee_admin_user_id": str(b.admin_id)}).status_code == 409  # already a's
    assert client.post(f"{ADM}/tickets/{tid}/assign", headers=a.h,
                       json={"assignee_admin_user_id": str(b.admin_id)}).status_code == 403  # hand-off is a manager's
    # unknown assignee
    assert client.post(f"{ADM}/tickets/{tid}/assign", headers=boss.h,
                       json={"assignee_admin_user_id": str(uuid4())}).status_code in (400, 404)


async def test_status_transitions_through_the_api(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    assert status_of(a.h, tid, "CLOSED").status_code == 409  # cannot skip
    assert status_of(a.h, tid, "OPEN").status_code == 409
    assert status_of(a.h, tid, "IN_PROGRESS").json()["status"] == "IN_PROGRESS"
    assert status_of(a.h, tid, "WAITING_ON_CUSTOMER", "need a screenshot").json()["status"] == "WAITING_ON_CUSTOMER"
    assert status_of(a.h, tid, "RESOLVED").status_code == 400  # resolution message required
    assert status_of(a.h, tid, "RESOLVED", "short").status_code == 400
    done = status_of(a.h, tid, "RESOLVED", "Refund was credited on the 5th")
    assert done.status_code == 200 and done.json()["resolved_at"]
    assert status_of(a.h, tid, "OPEN").status_code == 409
    assert status_of(a.h, tid, "CLOSED").json()["closed_at"]
    assert status_of(a.h, tid, "IN_PROGRESS").status_code == 409  # closed is final
    for path, body in (("replies", {"message": "late reply"}), ("notes", {"note": "late note"}),
                       ("priority", {"priority": "LOW"})):
        assert client.post(f"{ADM}/tickets/{tid}/{path}", headers=a.h, json=body).status_code == 409
    assert status_of(a.h, tid, "NOPE").status_code == 422
    # the resolution text is what the customer reads
    mine = client.get(f"{ME}/tickets/{tid}", headers=c.h).json()
    assert any(e["from"] == "SUPPORT" and e["body"] == "Refund was credited on the 5th" for e in mine["events"])
    assert "SUPPORT_TICKET_STATUS_CHANGED" in await audit(db_session)


async def test_customer_reply_reopens_and_window_expires(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    status_of(a.h, tid, "WAITING_ON_CUSTOMER", "need more info")
    back = client.post(f"{ME}/tickets/{tid}/messages", headers=c.h, json={"message": "here is more"})
    assert back.status_code == 200 and back.json()["status"] == "IN_PROGRESS"
    status_of(a.h, tid, "RESOLVED", "Sorted out for you")
    reopened = client.post(f"{ME}/tickets/{tid}/messages", headers=c.h, json={"message": "still broken"})
    assert reopened.json()["status"] == "IN_PROGRESS"
    status_of(a.h, tid, "RESOLVED", "Sorted out again")
    real = support_service.utcnow
    monkeypatch.setattr(support_service, "utcnow", lambda: real() + timedelta(days=8))
    late = client.post(f"{ME}/tickets/{tid}/messages", headers=c.h, json={"message": "one more thing"})
    assert late.status_code == 409
    monkeypatch.setattr(support_service, "utcnow", real)
    status_of(a.h, tid, "CLOSED")
    assert client.post(f"{ME}/tickets/{tid}/messages", headers=c.h, json={"message": "hello?"}).status_code == 409


async def test_priority_and_summary(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    assert client.post(f"{ADM}/tickets/{tid}/priority", headers=a.h, json={"priority": "URGENT"}).json()["priority"] == "URGENT"
    assert client.post(f"{ADM}/tickets/{tid}/priority", headers=a.h, json={"priority": "BAD"}).status_code == 422
    assert "SUPPORT_TICKET_PRIORITY_CHANGED" in await audit(db_session)
    rows = client.get(f"{ADM}/summary", headers=a.h).json()
    assert {"status": "OPEN", "kind": "ISSUE", "count": 1} in rows


async def test_filters(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    t1 = new_ticket(c.h, kind="COMPLAINT", category="CHARGES").json()["id"]
    t2 = new_ticket(c.h, kind="QUESTION", category="KYC").json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    ids = lambda q: {t["id"] for t in client.get(f"{ADM}/tickets{q}", headers=a.h).json()}  # noqa: E731
    assert ids("?kind=COMPLAINT") == {t1} and ids("?category=KYC") == {t2}
    assert ids("?unassigned=true") == {t1, t2} and ids("?mine=true") == set()
    status_of(a.h, t2, "IN_PROGRESS")
    assert ids("?mine=true") == {t2} and ids("?status=IN_PROGRESS") == {t2} and ids("?unassigned=true") == {t1}
    assert client.get(f"{ADM}/tickets?status=BOGUS", headers=a.h).status_code == 422


async def test_complaint_sla_overdue_flag(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h, kind="COMPLAINT", category="CHARGES").json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    assert client.get(f"{ADM}/tickets?overdue=true", headers=a.h).json() == []
    real = support_service.utcnow
    monkeypatch.setattr(support_service, "utcnow", lambda: real() + timedelta(days=31))
    late = client.get(f"{ADM}/tickets?overdue=true", headers=a.h).json()
    assert [t["id"] for t in late] == [tid] and late[0]["overdue"] is True
    monkeypatch.setattr(support_service, "utcnow", real)
    assert client.get(f"{ADM}/tickets/{tid}", headers=a.h).json()["overdue"] is False


async def test_escalation(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    comp = new_ticket(c.h, kind="COMPLAINT", category="CHARGES").json()["id"]
    issue = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    boss = await actor(monkeypatch, db_session, "SUPER_ADMIN")
    why = {"reason": "Customer unhappy with first answer"}
    assert client.post(f"{ADM}/tickets/{comp}/escalate", headers=a.h, json=why).status_code == 403
    assert client.post(f"{ADM}/tickets/{comp}/escalate", headers=boss.h, json={"reason": "short"}).status_code == 422
    assert client.post(f"{ADM}/tickets/{issue}/escalate", headers=boss.h, json=why).status_code == 409
    assert client.post(f"{ADM}/tickets/{comp}/escalate", headers=boss.h, json=why).json()["escalation_level"] == 1
    assert client.post(f"{ADM}/tickets/{comp}/escalate", headers=boss.h, json=why).json()["escalation_level"] == 2
    assert client.post(f"{ADM}/tickets/{comp}/escalate", headers=boss.h, json=why).status_code == 409
    assert "SUPPORT_COMPLAINT_ESCALATED" in await audit(db_session)
    # customers never learn about escalation
    assert "ESCALATED" not in str(client.get(f"{ME}/tickets/{comp}", headers=c.h).json())


# --------------------------------------------------------- notifications


async def approved_template(db_session, key, body):
    await db_session.execute(text(
        "INSERT INTO notification_templates (id, template_key, locale, version, channel, category, status, body, "
        "allowed_variables, approved_at, created_at, updated_at) VALUES (gen_random_uuid(), :k, 'en', 1, 'SMS', "
        "'SERVICE', 'APPROVED', :b, '[\"ticket_number\"]'::jsonb, now(), now(), now())"), {"k": key, "b": body})
    await db_session.commit()


async def test_notifications_are_queued_once_per_event(monkeypatch, db_session):
    for key in ("support.ticket_received", "support.ticket_replied", "support.ticket_resolved"):
        await approved_template(db_session, key, "Request {ticket_number} update.")
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    client.post(f"{ADM}/tickets/{tid}/replies", headers=a.h, json={"message": "We are checking"})
    status_of(a.h, tid, "RESOLVED", "All done and fixed")
    db_session.expire_all()
    keys = [n.template_key for (n,) in await db_session.execute(select(Notification))]
    assert sorted(keys) == ["support.ticket_received", "support.ticket_replied", "support.ticket_resolved"]
    # the stored notification holds no message text and no phone number
    blob = str([(n.variables, n.dedupe_key) for (n,) in await db_session.execute(select(Notification))])
    assert c.phone not in blob and "We are checking" not in blob


async def test_ticket_works_without_templates(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    assert new_ticket(c.h).status_code == 201  # no template yet: the ticket still opens


# ------------------------------------------------- database protections


async def test_event_history_is_append_only(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    with pytest.raises(DBAPIError):
        await db_session.execute(update(SupportTicketEvent).where(SupportTicketEvent.ticket_id == tid).values(body="edited"))
    await db_session.rollback()
    with pytest.raises(DBAPIError):
        await db_session.execute(text("DELETE FROM support_ticket_events"))
    await db_session.rollback()


async def test_tickets_cannot_be_deleted_or_reopened_after_close(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h).json()["id"]
    a = await actor(monkeypatch, db_session, "CUSTOMER_SUPPORT")
    with pytest.raises(DBAPIError):
        await db_session.execute(text("DELETE FROM support_tickets"))
    await db_session.rollback()
    status_of(a.h, tid, "RESOLVED", "Fixed it for you")
    status_of(a.h, tid, "CLOSED")
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE support_tickets SET status='IN_PROGRESS', closed_at=NULL"))
    await db_session.rollback()


async def test_database_blocks_bad_rows(monkeypatch, db_session):
    c = await actor(monkeypatch, db_session)
    tid = new_ticket(c.h, kind="COMPLAINT", category="CHARGES").json()["id"]
    for sql in (
        "UPDATE support_tickets SET user_id = gen_random_uuid()",                  # identity is fixed
        "UPDATE support_tickets SET escalation_level = 0 WHERE kind='COMPLAINT'; "
        "UPDATE support_tickets SET escalation_level = 1; UPDATE support_tickets SET escalation_level = 0",
        "UPDATE support_tickets SET status = 'BOGUS'",
        "UPDATE support_tickets SET sensitive = true",                              # must follow the category
        "UPDATE support_tickets SET kind = 'QUESTION'",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()
    with pytest.raises(DBAPIError):  # internal event kinds cannot be customer-visible
        await db_session.execute(text(
            "INSERT INTO support_ticket_events (id, ticket_id, event_type, visibility, actor_type, created_at) "
            "VALUES (gen_random_uuid(), :t, 'INTERNAL_NOTE', 'CUSTOMER', 'ADMIN', now())"), {"t": tid})
    await db_session.rollback()


async def test_ticket_numbers_unique_under_concurrency(monkeypatch, db_session):
    users = [await actor(monkeypatch, db_session) for _ in range(5)]
    results = await asyncio.gather(*[asyncio.to_thread(new_ticket, u.h) for u in users])
    assert all(r.status_code == 201 for r in results)
    nums = [r.json()["ticket_number"] for r in results]
    assert len(set(nums)) == 5
    db_session.expire_all()
    assert (await db_session.execute(select(func.count()).select_from(SupportTicket))).scalar_one() == 5
