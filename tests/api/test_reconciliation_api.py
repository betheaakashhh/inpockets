"""2.14 reconciliation on real Postgres with the development providers."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.domain import reconciliation as dom
from app.domain.repayment import today_ist
from app.main import app
from app.models.audit_log import AuditLog
from app.models.disbursement import Disbursement
from app.models.ledger import LedgerTransaction
from app.models.reconciliation import ReconciliationRecord, ReconciliationRun
from app.models.repayment import RepaymentPayment
from app.providers.settlement import SettlementLine
from app.providers.settlement_development import DevelopmentSettlementProvider as Settle
import app.services.reconciliation as recon_service
from app.services.reconciliation_factory import build_reconciliation_service
from app.services.reconciliation_runner import run_reconciliation
from app.workers.reconciliation import run_once as run_worker
from tests.api.test_disbursement_api import ready  # noqa: F401
from tests.api.test_loan_offer_api import world  # noqa: F401
from tests.api.test_repayment_api import (  # noqa: F401
    active_loan,
    count,
    disbursed,
    env,
    fast_forward,
    make_actor,
    settle,
    started,
)

client = TestClient(app)
D = Decimal
BASE = "/api/v1/admin/reconciliation"
C, X = "COLLECTION", "DISBURSEMENT"


@pytest.fixture(autouse=True)
def settlement_reset():
    Settle.reset()
    yield
    Settle.reset()


def today():
    return today_ist()


def tomorrow():
    return today() + timedelta(days=1)


def L(ref, amount, status="SETTLED", line_id=None):
    return SettlementLine(line_id or f"line-{ref}", ref, D(str(amount)), status)


async def paid_loan(world, db_session, monkeypatch, amount="2500.00"):
    """An active loan with one successful customer payment."""
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, amount, db_session)
    settle(ref, "SUCCESS", amount=amount)
    r.pay_ref, r.amount = ref, D(amount)
    return r


async def payout_ref(db_session, offer_id):
    db_session.expire_all()
    d = (await db_session.execute(select(Disbursement).where(Disbursement.loan_offer_id == offer_id))).scalars().first()
    return d.provider_ref, d.amount


async def recon(flow, day=None, **kw):
    return await run_reconciliation(flow, day or today(), today=tomorrow(), **kw)


async def records(db_session, **where):
    db_session.expire_all()
    stmt = select(ReconciliationRecord).order_by(ReconciliationRecord.provider_ref)
    for k, v in where.items():
        stmt = stmt.where(getattr(ReconciliationRecord, k) == v)
    return list((await db_session.execute(stmt)).scalars())


async def runs(db_session):
    db_session.expire_all()
    return list((await db_session.execute(select(ReconciliationRun))).scalars())


async def actions(db_session):
    return [a for (a,) in await db_session.execute(select(AuditLog.action))]


# ------------------------------------------------------------ matching


async def test_perfect_match_collection(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00")]
    out = await recon(C)
    assert out.status == "COMPLETED" and out.discrepancies == 0
    (rec,) = await records(db_session)
    assert (rec.status, rec.discrepancy, rec.review_status) == ("MATCHED", None, "NOT_REQUIRED")
    assert rec.internal_amount == D("2500.00") and rec.external_amount == D("2500.00")
    assert rec.ledger_net == D("2500.00") == rec.expected_ledger_net
    (run,) = await runs(db_session)
    assert (run.status, run.matched_count, run.internal_count, run.external_count) == ("COMPLETED", 1, 1, 1)
    assert run.completed_at is not None


async def test_perfect_match_disbursement_checks_the_books_too(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    ref, amount = await payout_ref(db_session, r.offer_id)
    Settle.reports[(X, today())] = [L(ref, amount)]
    out = await recon(X)
    assert out.discrepancies == 0
    (rec,) = await records(db_session)
    assert rec.status == "MATCHED" and rec.ledger_net == -amount


async def test_missing_external_event(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    out = await recon(C)  # the bank report is empty
    assert out.discrepancies == 1
    (rec,) = await records(db_session)
    assert (rec.status, rec.discrepancy, rec.review_status) == ("UNMATCHED", "MISSING_EXTERNAL", "OPEN")
    assert rec.provider_ref == r.pay_ref and rec.external_count == 0


async def test_missing_internal_event(world, db_session, monkeypatch):
    Settle.reports[(C, today())] = [L("bank-only-ref", "700.00")]
    await recon(C)
    (rec,) = await records(db_session)
    assert (rec.status, rec.discrepancy) == ("UNMATCHED", "MISSING_INTERNAL")
    assert rec.internal_id is None and rec.external_amount == D("700.00")


async def test_amount_mismatch(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2400.00")]
    await recon(C)
    (rec,) = await records(db_session)
    assert (rec.status, rec.discrepancy) == ("MISMATCH", "AMOUNT_MISMATCH")
    assert (rec.internal_amount, rec.external_amount) == (D("2500.00"), D("2400.00"))


async def test_status_mismatch(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00", status="FAILED")]
    await recon(C)
    (rec,) = await records(db_session)
    assert (rec.status, rec.discrepancy) == ("MISMATCH", "STATUS_MISMATCH")


async def test_duplicate_external_event_is_one_flagged_finding(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00", line_id="A"), L(r.pay_ref, "2500.00", line_id="B")]
    out = await recon(C)
    assert out.discrepancies == 1
    (rec,) = await records(db_session)
    assert (rec.status, rec.discrepancy, rec.external_count) == ("REQUIRES_REVIEW", "DUPLICATE_EXTERNAL", 2)


async def test_a_discrepancy_never_changes_payments_payouts_or_the_ledger(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "1.00"), L("ghost", "9.00")]

    async def snapshot():
        db_session.expire_all()
        pays = (await db_session.execute(select(RepaymentPayment.id, RepaymentPayment.status, RepaymentPayment.amount, RepaymentPayment.updated_at))).all()
        txs = (await db_session.execute(select(func.count(), func.sum(LedgerTransaction.total_amount)).select_from(LedgerTransaction))).one()
        return [tuple(p) for p in pays], tuple(txs)

    before = await snapshot()
    out = await recon(C)
    assert out.discrepancies == 2
    assert await snapshot() == before


# ----------------------------------------------------------- run safety


async def test_a_completed_day_is_not_redone(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00")]
    assert (await recon(C)).status == "COMPLETED"
    calls = len(Settle.fetch_calls)
    again = await recon(C)
    assert again.status == "SKIPPED" and again.claim.reason == "already_completed"
    assert len(Settle.fetch_calls) == calls
    assert len(await records(db_session)) == 1


async def test_provider_down_fails_the_run_then_a_retry_completes_it(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00")]
    Settle.behaviour = "down"
    out = await recon(C)
    assert out.status == "FAILED"
    (run,) = await runs(db_session)
    assert (run.status, run.attempts) == ("FAILED", 1) and "SettlementUnavailable" in run.error
    assert await records(db_session) == []  # nothing half-written
    Settle.behaviour = "ok"
    out = await recon(C)
    assert out.status == "COMPLETED"
    (run,) = await runs(db_session)
    assert (run.status, run.attempts, run.error) == ("COMPLETED", 2, None)
    assert len(await records(db_session)) == 1


async def test_a_malformed_report_trusts_nothing(world, db_session, monkeypatch):
    Settle.reports[(C, today())] = [L("x", "-5.00")]
    out = await recon(C)
    assert out.status == "FAILED" and await records(db_session) == []
    Settle.reports[(C, today())] = [SettlementLine("l", "x", D("5"), "WEIRD")]
    assert (await recon(C)).status == "FAILED"
    Settle.behaviour = "malformed"
    assert (await recon(C)).status == "FAILED"


async def test_an_oversized_report_fails_instead_of_half_running(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "reconciliation_max_lines", 1)
    Settle.reports[(C, today())] = [L("a", 1), L("b", 2)]
    assert (await recon(C)).status == "FAILED"
    assert await records(db_session) == []


async def test_today_and_the_future_cannot_be_reconciled(world, db_session, monkeypatch):
    with pytest.raises(dom.ReconciliationError):
        await run_reconciliation(C, today(), today=today())
    with pytest.raises(dom.ReconciliationError):
        await run_reconciliation(C, today() + timedelta(days=5), today=today())
    assert await runs(db_session) == []


async def test_a_running_day_is_skipped_until_it_looks_crashed(world, db_session, monkeypatch):
    svc = build_reconciliation_service(db_session)
    first = await svc.claim(C, today(), today=tomorrow())
    await db_session.commit()
    assert first.reason == "claimed"
    second = await build_reconciliation_service(db_session).claim(C, today(), today=tomorrow())
    assert second.reason == "in_progress" and second.run_id == first.run_id
    real = recon_service.utcnow
    monkeypatch.setattr(recon_service, "utcnow", lambda: real() + timedelta(minutes=30))
    third = await build_reconciliation_service(db_session).claim(C, today(), today=tomorrow())
    await db_session.commit()
    assert third.reason == "retaken" and third.run_id == first.run_id
    (run,) = await runs(db_session)
    assert run.attempts == 2


async def test_two_workers_claiming_at_once_only_one_proceeds(world, db_session, monkeypatch):
    from app.db.session import AsyncSessionLocal

    async def attempt():
        async with AsyncSessionLocal() as s:
            res = await build_reconciliation_service(s).claim(C, today(), today=tomorrow())
            await s.commit()
            return res.reason

    reasons = await asyncio.gather(*(attempt() for _ in range(5)))
    assert reasons.count("claimed") == 1
    assert len(await runs(db_session)) == 1


# --------------------------------------------------------------- worker


async def test_worker_covers_recent_days_for_both_flows_and_is_idempotent(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00")]
    # "tomorrow" is the worker's today, so the lookback is today-2 .. today
    stats = await run_worker(today=tomorrow())
    assert stats["completed"] == 6 and stats["failed"] == 0 and stats["errors"] == 0
    assert stats["discrepancies"] == 1  # the payout we made today is not in the bank report
    assert len(await runs(db_session)) == 6
    again = await run_worker(today=tomorrow())
    assert again["completed"] == 0 and again["skipped"] == 0
    assert len(await runs(db_session)) == 6


async def test_worker_retries_failures_then_gives_up_at_the_limit(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "reconciliation_max_attempts", 2)
    monkeypatch.setattr(get_settings(), "reconciliation_lookback_days", 1)
    Settle.behaviour = "down"
    assert (await run_worker(today=tomorrow()))["failed"] == 2  # both flows, attempt 1
    assert (await run_worker(today=tomorrow()))["failed"] == 2  # attempt 2
    third = await run_worker(today=tomorrow())
    assert third == {"completed": 0, "failed": 0, "skipped": 0, "discrepancies": 0, "errors": 0}
    assert {r.attempts for r in await runs(db_session)} == {2}
    Settle.behaviour = "ok"  # an admin can still start a given-up day
    _, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    day = today()
    fast_forward(monkeypatch, days=1)
    response = client.post(f"{BASE}/runs", json={"flow": C, "report_date": str(day)}, headers=headers)
    assert response.status_code == 200 and response.json()["outcome"] == "COMPLETED"
    assert response.json()["run"]["attempts"] == 3


# ------------------------------------------------------------ admin API


async def test_admin_can_start_a_run_and_a_completed_day_is_refused(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00")]
    admin, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    body = {"flow": C, "report_date": str(today())}
    fast_forward(monkeypatch, days=1)
    first = client.post(f"{BASE}/runs", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["outcome"] == "COMPLETED" and first.json()["run"]["matched_count"] == 1
    second = client.post(f"{BASE}/runs", json=body, headers=headers)
    assert second.status_code == 409
    got = client.get(f"{BASE}/runs", headers=headers)
    assert got.status_code == 200 and len(got.json()) == 1
    one = client.get(f"{BASE}/runs/{got.json()[0]['id']}", headers=headers)
    assert one.status_code == 200
    assert "RECONCILIATION_RUN_STARTED" in await actions(db_session)
    assert "RECONCILIATION_RUN_COMPLETED" in await actions(db_session)


async def test_admin_start_of_today_is_a_clean_400(world, db_session, monkeypatch):
    admin, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    response = client.post(f"{BASE}/runs", json={"flow": C, "report_date": str(today())}, headers=headers)
    assert response.status_code == 400


async def test_permissions(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "1.00")]
    await recon(C)
    (rec,) = await records(db_session)
    _, finance = await make_actor(monkeypatch, db_session, role="FINANCE")
    _, auditor = await make_actor(monkeypatch, db_session, role="AUDITOR")
    _, support = await make_actor(monkeypatch, db_session, role="CUSTOMER_SUPPORT")
    day = str(today() - timedelta(days=1))
    assert client.get(f"{BASE}/records", headers=auditor).status_code == 200
    assert client.get(f"{BASE}/summary", headers=auditor).status_code == 200
    assert client.post(f"{BASE}/runs", json={"flow": C, "report_date": day}, headers=auditor).status_code == 403
    assert client.post(f"{BASE}/records/{rec.id}/start-review", headers=auditor).status_code == 403
    assert client.get(f"{BASE}/records", headers=support).status_code == 403
    assert client.post(f"{BASE}/runs", json={"flow": C, "report_date": day}, headers=support).status_code == 403
    assert client.get(f"{BASE}/records", headers=world.customer_headers).status_code == 403
    assert client.get(f"{BASE}/records").status_code in (401, 403)
    assert client.get(f"{BASE}/records", headers=finance).status_code == 200


async def test_review_workflow_and_the_open_summary(world, db_session, monkeypatch):
    r = await paid_loan(world, db_session, monkeypatch)
    Settle.reports[(C, today())] = [L(r.pay_ref, "2500.00"), L("ghost", "5.00")]
    await recon(C)
    _, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    summary = client.get(f"{BASE}/summary", headers=headers).json()
    assert summary["total_open"] == 1 and summary["rows"][0]["status"] == "UNMATCHED"
    ghost = next(x for x in await records(db_session) if x.provider_ref == "ghost")
    matched = next(x for x in await records(db_session) if x.provider_ref == r.pay_ref)

    assert client.post(f"{BASE}/records/{matched.id}/start-review", headers=headers).status_code == 409
    assert client.post(f"{BASE}/records/{matched.id}/resolve", json={"resolution": "EXPLAINED", "note": "nothing to resolve here"}, headers=headers).status_code == 409

    started = client.post(f"{BASE}/records/{ghost.id}/start-review", headers=headers)
    assert started.status_code == 200 and started.json()["review_status"] == "IN_REVIEW"
    assert client.post(f"{BASE}/records/{ghost.id}/start-review", headers=headers).status_code == 409
    short = client.post(f"{BASE}/records/{ghost.id}/resolve", json={"resolution": "EXPLAINED", "note": "short"}, headers=headers)
    assert short.status_code == 422
    bad = client.post(f"{BASE}/records/{ghost.id}/resolve", json={"resolution": "DELETE_IT", "note": "long enough note"}, headers=headers)
    assert bad.status_code == 422
    done = client.post(f"{BASE}/records/{ghost.id}/resolve", json={"resolution": "ESCALATED_TO_PROVIDER", "note": "raised ticket 4411 with the bank"}, headers=headers)
    assert done.status_code == 200 and done.json()["review_status"] == "RESOLVED"
    assert done.json()["resolution"] == "ESCALATED_TO_PROVIDER" and done.json()["reviewed_at"]
    assert client.post(f"{BASE}/records/{ghost.id}/resolve", json={"resolution": "EXPLAINED", "note": "second attempt note"}, headers=headers).status_code == 409
    assert client.get(f"{BASE}/summary", headers=headers).json()["total_open"] == 0
    got = client.get(f"{BASE}/records?review_status=RESOLVED", headers=headers).json()
    assert [x["provider_ref"] for x in got] == ["ghost"]
    assert client.get(f"{BASE}/records/{ghost.id}", headers=headers).status_code == 200
    assert client.get(f"{BASE}/records/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404
    acts = await actions(db_session)
    assert "RECONCILIATION_REVIEW_STARTED" in acts and "RECONCILIATION_FINDING_RESOLVED" in acts


async def test_resolving_directly_without_starting_review_is_allowed(world, db_session, monkeypatch):
    Settle.reports[(C, today())] = [L("ghost", "5.00")]
    await recon(C)
    (rec,) = await records(db_session)
    _, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    ok = client.post(f"{BASE}/records/{rec.id}/resolve", json={"resolution": "EXPLAINED", "note": "settled a day late, seen next day"}, headers=headers)
    assert ok.status_code == 200


# ------------------------------------------------------ database rules


async def test_findings_cannot_be_edited_or_deleted_and_resolved_is_final(world, db_session, monkeypatch):
    Settle.reports[(C, today())] = [L("ghost", "5.00")]
    await recon(C)
    (rec,) = await records(db_session)
    rec_id = rec.id
    for sql in (
        "UPDATE reconciliation_records SET status='MATCHED', discrepancy=NULL, review_status='NOT_REQUIRED'",
        "UPDATE reconciliation_records SET external_amount=1.00",
        "UPDATE reconciliation_records SET provider_ref='other'",
        "DELETE FROM reconciliation_records",
        "DELETE FROM reconciliation_runs",
        "UPDATE reconciliation_runs SET report_date = report_date + 1",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()
    # a resolved row is final, and a completed run is final
    _, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    assert client.post(f"{BASE}/records/{rec_id}/resolve", json={"resolution": "EXPLAINED", "note": "explained well enough"}, headers=headers).status_code == 200
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE reconciliation_records SET review_note='rewritten'"))
    await db_session.rollback()
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE reconciliation_runs SET matched_count = 99"))
    await db_session.rollback()


async def test_database_refuses_incoherent_rows(world, db_session, monkeypatch):
    Settle.reports[(C, today())] = [L("ghost", "5.00")]
    await recon(C)
    (run,) = await runs(db_session)
    run_id = run.id
    base = ("INSERT INTO reconciliation_records (id, run_id, flow, provider, provider_ref, status, discrepancy, detail, "
            "external_count, review_status) VALUES (gen_random_uuid(), :r, 'COLLECTION', 'development', :ref, :st, :d, 'x', 0, :rs)")
    for params in (
        {"ref": "a", "st": "MATCHED", "d": "AMOUNT_MISMATCH", "rs": "NOT_REQUIRED"},  # matched with a discrepancy
        {"ref": "b", "st": "UNMATCHED", "d": None, "rs": "OPEN"},  # a problem with no kind
        {"ref": "c", "st": "UNMATCHED", "d": "MISSING_EXTERNAL", "rs": "NOT_REQUIRED"},  # a problem needing no review
        {"ref": "d", "st": "UNMATCHED", "d": "MISSING_EXTERNAL", "rs": "RESOLVED"},  # resolved with no note
        {"ref": "ghost", "st": "UNMATCHED", "d": "MISSING_EXTERNAL", "rs": "OPEN"},  # one finding per reference per run
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(base), {"r": run_id, **params})
        await db_session.rollback()
