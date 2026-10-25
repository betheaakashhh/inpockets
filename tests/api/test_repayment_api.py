"""2.12 repayment tests on real Postgres with the development providers."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.domain import ledger as L
from app.domain import repayment as dom
from app.main import app
from app.models.audit_log import AuditLog
from app.models.ledger import LedgerEntry, LedgerTransaction
from app.models.repayment import (
    RepaymentAllocation,
    RepaymentEvent,
    RepaymentInstallment,
    RepaymentPayment,
    RepaymentSchedule,
)
from app.providers.bank_verification_development import (
    DevelopmentBankVerificationProvider as DevBank,
)
from app.providers.disbursement_development import DevelopmentDisbursementProvider as Dev
from app.providers.esign_development import DevelopmentESignProvider as DevESign
from app.providers.payment_development import (
    DevelopmentPaymentProvider as Pay,
    sign_webhook,
)
from app.services.ledger_factory import build_ledger_service
from app.workers.disbursement import run_once as run_disbursements
from app.workers.repayment import run_once as run_repayments
from tests.api import test_loan_offer_api as loan_offer_tests
from tests.api.test_bank_verification_api import FP, K1, K2
from tests.api.test_disbursement_api import (  # noqa: F401
    NUMBER,
    SECRET as DISB_SECRET,
    create as create_disbursement,
    ready,
)
from tests.api.test_esign_api import SIGNED_PDF  # noqa: F401
from tests.api.test_loan_offer_api import issued_offer, make_actor as _make_actor, world  # noqa: F401

client = TestClient(app)
D = Decimal
SECRET = "payment-test-secret"
PROVIDER = "development"
PRINCIPAL = D("5000.00")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "payment_webhook_secret", SECRET)
    monkeypatch.setattr(s, "disbursement_webhook_secret", DISB_SECRET)
    monkeypatch.setattr(s, "esign_webhook_secret", "unit-test-webhook-secret")
    monkeypatch.setattr(s, "esign_require_signed_artifact", True)
    monkeypatch.setattr(s, "field_encryption_keys", f"k1:{K1},k2:{K2}")
    monkeypatch.setattr(s, "field_encryption_active_key_id", "k1")
    monkeypatch.setattr(s, "bank_fingerprint_key", FP)
    monkeypatch.setattr(s, "rate_limit_sensitive_per_minute", 1000)
    monkeypatch.setattr(s, "rate_limit_user_per_minute", 1000)
    monkeypatch.setattr(s, "rate_limit_webhook_per_minute", 1000)
    for p in (Dev, DevESign, DevBank, Pay):
        p.reset()
    yield
    for p in (Dev, DevESign, DevBank, Pay):
        p.reset()


# ------------------------------------------------------------------ helpers


async def make_actor(monkeypatch, db_session, *, role=None):
    row, headers = await _make_actor(monkeypatch, db_session, role=role)
    return SimpleNamespace(id=row.id), headers


async def disbursed(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    Dev.behaviour = "instant"
    assert create_disbursement(r.finance_headers, r.offer_id).status_code == 201
    await run_disbursements()
    return r


def schedule_url(path=""):
    return f"/api/v1/admin/repayments/schedules{path}"


def make_schedule(r, count=2, **extra):
    return client.post(
        schedule_url(),
        json={"loan_offer_id": r.offer_id, "installment_count": count, **extra},
        headers=r.finance_headers,
    )


async def active_loan(world, db_session, monkeypatch, count=2):
    r = await disbursed(world, db_session, monkeypatch)
    created = make_schedule(r, count)
    assert created.status_code == 201, created.text
    r.schedule_id = created.json()["id"]
    activated = client.post(schedule_url(f"/{r.schedule_id}/activate"), headers=r.finance_headers)
    assert activated.status_code == 200, activated.text
    return r


def pay(world, r, amount, key=None, headers=None):
    h = dict(headers or world.customer_headers)
    h["Idempotency-Key"] = key or f"key-{uuid4()}"
    return client.post(
        f"/api/v1/loan-offers/{r.offer_id}/repayments", json={"amount": str(amount)}, headers=h
    )


def hook(ref, status, *, amount=None, event_id=None, secret=SECRET, timestamp=None, **extra):
    payload = {
        "event_id": event_id or f"evt-{uuid4()}",
        "provider_ref": ref,
        "status": status,
        "amount": str(amount) if amount is not None else None,
        "occurred_at": dom.utcnow().isoformat(),
        **extra,
    }
    body = json.dumps(payload).encode()
    headers = sign_webhook(secret, body, timestamp) if secret else {}
    headers["Content-Type"] = "application/json"
    return body, headers


def post_hook(body, headers, provider=PROVIDER):
    return client.post(f"/api/v1/webhooks/payment/{provider}", content=body, headers=headers)


def settle(ref, status="SUCCESS", amount=None, **kw):
    body, headers = hook(ref, status, amount=amount, **kw)
    response = post_hook(body, headers)
    assert response.status_code == 200, response.text
    return response.json()["outcome"]


async def row(db_session, payment_id):
    db_session.expire_all()
    p = (
        await db_session.execute(select(RepaymentPayment).where(RepaymentPayment.id == payment_id))
    ).scalar_one()
    return SimpleNamespace(**{c.name: getattr(p, c.name) for c in p.__table__.columns})


async def installments(db_session, schedule_id):
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(RepaymentInstallment)
            .where(RepaymentInstallment.schedule_id == schedule_id)
            .order_by(RepaymentInstallment.installment_number)
        )
    ).scalars().all()
    return [
        SimpleNamespace(**{c.name: getattr(i, c.name) for c in i.__table__.columns}) for i in rows
    ]


async def count(db_session, model, *where) -> int:
    db_session.expire_all()
    return (
        await db_session.execute(select(func.count()).select_from(model).where(*where))
    ).scalar_one()


async def started(world, r, amount, db_session):
    """Start a payment and return (id, provider_ref)."""
    response = pay(world, r, amount)
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    return pid, (await row(db_session, pid)).provider_ref


async def audit_actions(db_session, entity_id=None):
    stmt = select(AuditLog.action)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == str(entity_id))
    return [r[0] for r in await db_session.execute(stmt)]


def fast_forward(monkeypatch, **delta):
    real = dom.utcnow
    monkeypatch.setattr(dom, "utcnow", lambda: real() + timedelta(**delta))


def my_schedule(world, r):
    return client.get(
        f"/api/v1/loan-offers/{r.offer_id}/repayment-schedule", headers=world.customer_headers
    )


# ======================================================================
# Schedules
# ======================================================================


async def test_schedule_is_built_from_stored_terms_and_the_disbursed_amount(
    world, db_session, monkeypatch
):
    r = await disbursed(world, db_session, monkeypatch)
    response = make_schedule(r, 2)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "DRAFT" and body["principal_total"] == "5000.00"
    assert body["total_payable"] == "5000.00" and body["interest_total"] == "0.00"
    items = body["installments"]
    assert [i["principal_due"] for i in items] == ["2500.00", "2500.00"]
    assert all(i["status"] == "SCHEDULED" and i["fee_due"] == "0.00" for i in items)
    assert items[0]["due_date"] < items[1]["due_date"]
    assert body["ledger_principal_outstanding"] == "5000.00"
    assert body["ledger_matches_schedule"] is True
    assert "REPAYMENT_SCHEDULE_CREATED" in await audit_actions(db_session)


async def test_schedule_request_cannot_carry_amounts_dates_or_rates(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    for extra in ({"principal": "1.00"}, {"interest_total": "9"}, {"first_due_date": "2030-01-01"}):
        response = client.post(
            schedule_url(),
            json={"loan_offer_id": r.offer_id, **extra},
            headers=r.finance_headers,
        )
        assert response.status_code == 422, extra


async def test_schedule_needs_a_paid_out_loan(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)  # accepted + signed, never disbursed
    response = make_schedule(r)
    assert response.status_code == 409 and "not been disbursed" in response.text
    # A payout that is only PROCESSING is not enough either.
    Dev.behaviour = "ok"
    assert create_disbursement(r.finance_headers, r.offer_id).status_code == 201
    await run_disbursements()
    assert make_schedule(r).status_code == 409


async def test_one_live_schedule_per_loan(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    assert make_schedule(r).status_code == 201
    assert make_schedule(r).status_code == 409
    assert await count(db_session, RepaymentSchedule) == 1


async def test_schedule_cannot_run_past_the_offer_tenure(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)  # tenure is 30 days
    assert make_schedule(r, 2, interval_days=16).status_code == 409
    assert make_schedule(r, 2, interval_days=15).status_code == 201


async def test_draft_is_hidden_from_the_customer_until_activated(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    sid = make_schedule(r).json()["id"]
    assert my_schedule(world, r).status_code == 404
    assert client.post(schedule_url(f"/{sid}/activate"), headers=r.finance_headers).status_code == 200
    shown = my_schedule(world, r)
    assert shown.status_code == 200 and shown.json()["status"] == "ACTIVE"
    assert "user_id" not in shown.json() and "disbursement_id" not in shown.json()
    again = client.post(schedule_url(f"/{sid}/activate"), headers=r.finance_headers)
    assert again.status_code == 409


async def test_a_draft_can_be_cancelled_and_replaced_but_an_active_schedule_cannot(
    world, db_session, monkeypatch
):
    r = await disbursed(world, db_session, monkeypatch)
    sid = make_schedule(r, 3).json()["id"]
    short = client.post(schedule_url(f"/{sid}/cancel"), json={"reason": "too short"}, headers=r.finance_headers)
    assert short.status_code == 409
    done = client.post(
        schedule_url(f"/{sid}/cancel"), json={"reason": "wrong installment count"}, headers=r.finance_headers
    )
    assert done.status_code == 200 and done.json()["status"] == "CANCELLED"
    replacement = make_schedule(r, 2)
    assert replacement.status_code == 201
    new_id = replacement.json()["id"]
    assert client.post(schedule_url(f"/{new_id}/activate"), headers=r.finance_headers).status_code == 200
    locked = client.post(
        schedule_url(f"/{new_id}/cancel"), json={"reason": "change of mind later"}, headers=r.finance_headers
    )
    assert locked.status_code == 409
    actions = await audit_actions(db_session)
    assert "REPAYMENT_SCHEDULE_CANCELLED" in actions and "REPAYMENT_SCHEDULE_ACTIVATED" in actions


async def test_schedule_management_is_permission_controlled(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    auditor, auditor_headers = await make_actor(monkeypatch, db_session, role="AUDITOR")
    body = {"loan_offer_id": r.offer_id, "installment_count": 2}
    assert client.post(schedule_url(), json=body, headers=auditor_headers).status_code == 403
    assert client.post(schedule_url(), json=body, headers=world.admin_headers).status_code == 403
    assert client.post(schedule_url(), json=body, headers=world.customer_headers).status_code == 403
    assert client.post(schedule_url(), json=body).status_code in (401, 403)
    sid = make_schedule(r).json()["id"]
    # Read-only roles may read, never change.
    assert client.get(schedule_url(f"/{sid}"), headers=auditor_headers).status_code == 200
    assert client.post(schedule_url(f"/{sid}/activate"), headers=auditor_headers).status_code == 403
    assert client.get(schedule_url(f"/{sid}"), headers=world.admin_headers).status_code == 403


# ---------------------------------------------- active schedule is immutable


@pytest.mark.parametrize(
    "sql,fragment",
    [
        ("UPDATE repayment_installments SET due_date = due_date + 1", "immutable"),
        ("UPDATE repayment_installments SET principal_due = principal_due + 1", "immutable"),
        ("UPDATE repayment_installments SET installment_number = 9", "immutable"),
        ("UPDATE repayment_schedules SET principal_total = 1", "immutable"),
        ("UPDATE repayment_schedules SET status = 'CANCELLED', cancelled_at = now()", "immutable"),
        ("DELETE FROM repayment_installments", "cannot be deleted"),
        ("DELETE FROM repayment_schedules", "cannot be deleted"),
    ],
)
async def test_active_schedule_terms_are_immutable_in_the_database(
    world, db_session, monkeypatch, sql, fragment
):
    await active_loan(world, db_session, monkeypatch)
    with pytest.raises(DBAPIError, match=fragment):
        await db_session.execute(text(sql))
    await db_session.rollback()


async def test_installments_cannot_be_added_to_an_active_schedule(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    with pytest.raises(DBAPIError, match="draft schedule"):
        await db_session.execute(
            text(
                "INSERT INTO repayment_installments (id, schedule_id, installment_number, due_date, "
                "principal_due, interest_due, fee_due, principal_paid, interest_paid, fee_paid, status) "
                "VALUES (gen_random_uuid(), :s, 99, now()::date, 1, 0, 0, 0, 0, 0, 'SCHEDULED')"
            ),
            dict(s=r.schedule_id),
        )
    await db_session.rollback()


async def test_paid_amounts_can_never_exceed_what_is_due(world, db_session, monkeypatch):
    await active_loan(world, db_session, monkeypatch)
    with pytest.raises(DBAPIError):
        await db_session.execute(text("UPDATE repayment_installments SET principal_paid = principal_due + 1"))
    await db_session.rollback()
    with pytest.raises(DBAPIError):  # status must agree with the amounts
        await db_session.execute(text("UPDATE repayment_installments SET status = 'PAID'"))
    await db_session.rollback()


async def test_interest_is_refused_until_accounting_rules_are_enabled(world, db_session, monkeypatch):
    def with_rate(application_id, principal="5000.00"):
        return {
            "loan_application_id": application_id,
            "principal_amount": principal,
            "tenure_days": 30,
            "commercial_terms": {"interest_rate_percent_per_annum": "24"},
        }

    monkeypatch.setattr(loan_offer_tests, "draft_body", with_rate)
    r = await disbursed(world, db_session, monkeypatch)
    blocked = make_schedule(r, 1)
    assert blocked.status_code == 409 and "accounting rules" in blocked.text
    assert await count(db_session, RepaymentSchedule) == 0

    monkeypatch.setattr(get_settings(), "ledger_interest_fee_posting_enabled", True)
    created = make_schedule(r, 1)
    assert created.status_code == 201, created.text
    assert created.json()["interest_total"] == "98.63"  # 5000 * 24% * 30/365
    assert created.json()["total_payable"] == "5098.63"
    sid = created.json()["id"]
    assert client.post(schedule_url(f"/{sid}/activate"), headers=r.finance_headers).status_code == 200

    # A full payment splits across principal and interest income in the ledger.
    pid, ref = await started(world, r, "5098.63", db_session)
    assert settle(ref, "SUCCESS", amount="5098.63") == "SUCCESS"
    p = await row(db_session, pid)
    assert (p.principal_applied, p.interest_applied, p.fee_applied, p.unapplied_amount) == (
        D("5000.00"), D("98.63"), D("0.00"), D("0.00"),
    )
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.INTEREST_INCOME].balance == D("98.63")
    assert balances[L.LOAN_PRINCIPAL].balance == 0


# ======================================================================
# Starting a payment
# ======================================================================


async def test_start_payment_records_intent_and_never_reports_success(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    response = pay(world, r, "1000.00")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PROCESSING" and body["amount"] == "1000.00"
    assert body["checkout_url"].startswith("https://pay.dev.invalid/")
    assert set(body) == {
        "id", "loan_offer_id", "status", "amount", "currency", "checkout_url",
        "requested_at", "completed_at",
    }  # no provider reference, idempotency key or internal status leaks
    p = await row(db_session, body["id"])
    assert p.status == "PENDING" and p.provider_ref and p.idempotency_key == f"inp-pay-{p.id}"
    assert len(Pay.transactions) == 1 and Pay.transactions[p.idempotency_key]["amount"] == D("1000.00")
    # Nothing is paid and nothing is booked until the provider confirms.
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 0
    assert "REPAYMENT_INITIATED" in await audit_actions(db_session, p.id)


async def test_a_client_cannot_mark_a_payment_successful(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    for extra in ({"status": "SUCCESS"}, {"status": "PAID"}, {"provider_ref": "x"}, {"paid": True}):
        h = {**world.customer_headers, "Idempotency-Key": f"key-{uuid4()}"}
        response = client.post(
            f"/api/v1/loan-offers/{r.offer_id}/repayments",
            json={"amount": "100.00", **extra},
            headers=h,
        )
        assert response.status_code == 422, extra
    pid, ref = await started(world, r, "100.00", db_session)
    # No customer or admin route can set a status on an existing payment.
    for method in ("put", "patch", "delete"):
        for path in (
            f"/api/v1/loan-offers/{r.offer_id}/repayments/{pid}",
            f"/api/v1/admin/repayments/payments/{pid}",
        ):
            response = client.request(
                method.upper(), path, json={"status": "SUCCESS"}, headers=world.customer_headers
            )
            assert response.status_code in (404, 405)
    assert (await row(db_session, pid)).status == "PENDING"


async def test_amount_validation(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    for bad in ("0", "-5.00", "1.005", "abc", "100000000000000"):
        assert pay(world, r, bad).status_code in (400, 409, 422), bad
    assert pay(world, r, "5000.01").status_code == 409  # more than is owed
    assert pay(world, r, "5000.00").status_code == 201  # exactly what is owed
    assert await count(db_session, RepaymentPayment) == 1


async def test_idempotency_key_is_required_and_well_formed(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    url = f"/api/v1/loan-offers/{r.offer_id}/repayments"
    assert client.post(url, json={"amount": "10.00"}, headers=world.customer_headers).status_code == 422
    for bad in ("short", "has space in it!", "x" * 101):
        h = {**world.customer_headers, "Idempotency-Key": bad}
        assert client.post(url, json={"amount": "10.00"}, headers=h).status_code == 400, bad
    assert await count(db_session, RepaymentPayment) == 0


async def test_duplicate_request_with_the_same_key_creates_one_payment(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    first = pay(world, r, "700.00", key="retry-key-0001")
    again = pay(world, r, "700.00", key="retry-key-0001")
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert await count(db_session, RepaymentPayment) == 1
    assert len(Pay.create_calls) == 1 and len(Pay.transactions) == 1  # provider hit once


async def test_the_same_key_with_a_different_request_is_refused(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    assert pay(world, r, "700.00", key="retry-key-0002").status_code == 201
    assert pay(world, r, "701.00", key="retry-key-0002").status_code == 409
    assert await count(db_session, RepaymentPayment) == 1


async def test_concurrent_duplicate_requests_create_one_payment(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)

    def go(_):
        return pay(world, r, "400.00", key="concurrent-key-1")

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(go, range(8)))
    assert {x.status_code for x in responses} <= {200, 201}
    assert len({x.json()["id"] for x in responses}) == 1
    assert await count(db_session, RepaymentPayment) == 1
    assert len(Pay.transactions) == 1


async def test_a_key_belongs_to_one_customer(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    other, other_headers = await make_actor(monkeypatch, db_session)
    assert pay(world, r, "10.00", key="shared-key-001").status_code == 201
    # Another customer cannot reuse it to reach, or replay, this loan.
    assert pay(world, r, "10.00", key="shared-key-001", headers=other_headers).status_code == 404
    assert await count(db_session, RepaymentPayment) == 1


async def test_customers_cannot_see_or_pay_other_customers_loans(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    other, other_headers = await make_actor(monkeypatch, db_session)
    assert pay(world, r, "10.00", headers=other_headers).status_code == 404
    assert client.get(
        f"/api/v1/loan-offers/{r.offer_id}/repayment-schedule", headers=other_headers
    ).status_code == 404
    assert client.get(f"/api/v1/loan-offers/{r.offer_id}/repayments", headers=other_headers).status_code == 404
    pid, _ = await started(world, r, "10.00", db_session)
    assert client.get(
        f"/api/v1/loan-offers/{r.offer_id}/repayments/{pid}", headers=other_headers
    ).status_code == 404
    assert client.get(f"/api/v1/loan-offers/{uuid4()}/repayments/{pid}", headers=world.customer_headers).status_code == 404


async def test_no_payment_without_an_active_schedule(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    assert pay(world, r, "10.00").status_code == 409  # none yet
    make_schedule(r)
    assert pay(world, r, "10.00").status_code == 409  # draft only


async def test_open_payments_per_loan_are_capped(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    for _ in range(dom.MAX_OPEN_PAYMENTS_PER_SCHEDULE):
        assert pay(world, r, "10.00").status_code == 201
    assert pay(world, r, "10.00").status_code == 409


# ======================================================================
# Webhooks: verification and authority
# ======================================================================


async def test_unsigned_or_badly_signed_callbacks_change_nothing(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)

    body, _ = hook(ref, "SUCCESS", amount="1000.00")
    assert post_hook(body, {"Content-Type": "application/json"}).status_code == 401
    body, headers = hook(ref, "SUCCESS", amount="1000.00", secret="wrong-secret")
    assert post_hook(body, headers).status_code == 401
    body, headers = hook(ref, "SUCCESS", amount="1000.00")
    headers["X-Payment-Signature"] = "0" * 64
    assert post_hook(body, headers).status_code == 401
    tampered, headers = hook(ref, "SUCCESS", amount="1000.00")
    assert post_hook(tampered.replace(b"1000.00", b"9999.00"), headers).status_code == 401
    # Stale (replayed) timestamp.
    body, headers = hook(ref, "SUCCESS", amount="1000.00", timestamp=int(dom.utcnow().timestamp()) - 3600)
    assert post_hook(body, headers).status_code == 401

    assert (await row(db_session, pid)).status == "PENDING"
    assert await count(db_session, RepaymentEvent) == 0
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 0


async def test_callbacks_are_rejected_when_no_secret_is_configured(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    monkeypatch.setattr(get_settings(), "payment_webhook_secret", None)
    body, headers = hook(ref, "SUCCESS", amount="1000.00", secret=SECRET)
    assert post_hook(body, headers).status_code == 401
    assert (await row(db_session, pid)).status == "PENDING"


async def test_malformed_unknown_and_oversized_callbacks(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)

    junk = b"not json"
    assert post_hook(junk, {**sign_webhook(SECRET, junk), "Content-Type": "application/json"}).status_code == 400
    for bad in (
        {"event_id": "e", "provider_ref": ref, "status": "NONSENSE"},
        {"provider_ref": ref, "status": "SUCCESS"},
        {"event_id": "e", "provider_ref": ref, "status": "SUCCESS", "amount": "abc"},
    ):
        raw = json.dumps(bad).encode()
        assert post_hook(raw, {**sign_webhook(SECRET, raw), "Content-Type": "application/json"}).status_code == 400
    body, headers = hook("dev-pay-unknown", "SUCCESS", amount="1.00")
    assert post_hook(body, headers).status_code == 404
    body, headers = hook(ref, "SUCCESS", amount="1000.00")
    assert post_hook(body, headers, provider="other-provider").status_code == 404
    big = b"x" * (1024 * 1024 + 1)
    assert post_hook(big, {**sign_webhook(SECRET, big), "Content-Type": "application/json"}).status_code == 413
    assert (await row(db_session, pid)).status == "PENDING"


# ======================================================================
# Verified success: allocation, ledger, partial / early / late
# ======================================================================


async def test_verified_success_allocates_and_posts_to_the_ledger(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "2500.00", db_session)
    assert settle(ref, "SUCCESS", amount="2500.00") == "SUCCESS"

    p = await row(db_session, pid)
    assert p.status == "SUCCESS" and p.completed_at is not None
    assert (p.principal_applied, p.unapplied_amount) == (D("2500.00"), D("0.00"))
    first, second = await installments(db_session, r.schedule_id)
    assert first.status == "PAID" and first.principal_paid == D("2500.00")
    assert second.status == "SCHEDULED" and second.principal_paid == 0

    tx = (
        await db_session.execute(select(LedgerTransaction).where(LedgerTransaction.kind == "REPAYMENT"))
    ).scalars().one()
    assert tx.total_amount == D("2500.00") and tx.source_id == p.id
    ledger = build_ledger_service(db_session)
    assert await ledger.principal_outstanding(r.offer_id) == D("2500.00")

    shown = my_schedule(world, r).json()
    assert shown["total_paid"] == "2500.00" and shown["total_remaining"] == "2500.00"
    mine = client.get(f"/api/v1/loan-offers/{r.offer_id}/repayments/{pid}", headers=world.customer_headers).json()
    assert mine["status"] == "PAID" and mine["checkout_url"] is None
    admin = client.get(schedule_url(f"/{r.schedule_id}"), headers=r.finance_headers).json()
    assert admin["ledger_matches_schedule"] is True  # books agree with the schedule
    assert "REPAYMENT_SUCCESS" in await audit_actions(db_session, pid)


async def test_partial_payments_accumulate_until_the_installment_is_paid(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    for chunk, expected_status, expected_paid in (
        ("1000.00", "PARTIALLY_PAID", D("1000.00")),
        ("1000.00", "PARTIALLY_PAID", D("2000.00")),
        ("500.00", "PAID", D("2500.00")),
    ):
        _, ref = await started(world, r, chunk, db_session)
        settle(ref, "SUCCESS", amount=chunk)
        first = (await installments(db_session, r.schedule_id))[0]
        assert (first.status, first.principal_paid) == (expected_status, expected_paid)
    assert (await installments(db_session, r.schedule_id))[1].status == "SCHEDULED"


async def test_early_payment_goes_to_the_earliest_unpaid_installments(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)  # nothing is due yet
    _, ref = await started(world, r, "3000.00", db_session)
    settle(ref, "SUCCESS", amount="3000.00")
    first, second = await installments(db_session, r.schedule_id)
    assert (first.status, first.principal_paid) == ("PAID", D("2500.00"))
    assert (second.status, second.principal_paid) == ("PARTIALLY_PAID", D("500.00"))
    # No rebate: the schedule's total payable is unchanged.
    assert my_schedule(world, r).json()["total_payable"] == "5000.00"


async def test_late_payment_is_flagged_overdue_without_inventing_fees(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    fast_forward(monkeypatch, days=20)  # past the first due date, before the second
    view = my_schedule(world, r).json()
    assert [i["status"] for i in view["installments"]] == ["OVERDUE", "SCHEDULED"]
    fast_forward(monkeypatch, days=20)  # both overdue now
    assert [i["status"] for i in my_schedule(world, r).json()["installments"]] == ["OVERDUE", "OVERDUE"]

    _, ref = await started(world, r, "2500.00", db_session)
    settle(ref, "SUCCESS", amount="2500.00")
    view = my_schedule(world, r).json()
    assert [i["status"] for i in view["installments"]] == ["PAID", "OVERDUE"]
    assert view["fee_total"] == "0.00" and view["total_payable"] == "5000.00"
    stored = await installments(db_session, r.schedule_id)
    assert all(i.fee_due == 0 and i.fee_paid == 0 for i in stored)  # no late fee exists
    assert stored[1].status == "SCHEDULED"  # OVERDUE is derived, never stored


async def test_full_repayment_closes_the_loan_and_blocks_further_payments(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    _, ref = await started(world, r, "5000.00", db_session)
    settle(ref, "SUCCESS", amount="5000.00")
    assert all(i.status == "PAID" for i in await installments(db_session, r.schedule_id))
    assert await build_ledger_service(db_session).principal_outstanding(r.offer_id) == 0
    assert pay(world, r, "1.00").status_code == 409  # fully repaid


# ======================================================================
# Duplicate / concurrent events
# ======================================================================


async def test_duplicate_webhook_event_is_applied_once(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    body, headers = hook(ref, "SUCCESS", amount="1000.00", event_id="evt-fixed")
    assert post_hook(body, headers).json()["outcome"] == "SUCCESS"
    assert post_hook(body, headers).json()["outcome"] == "DUPLICATE"
    assert post_hook(body, headers).json()["outcome"] == "DUPLICATE"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("1000.00")
    assert await count(db_session, RepaymentAllocation) == 1
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1
    assert await count(db_session, RepaymentEvent) == 1


async def test_same_fact_with_a_new_event_id_is_not_applied_twice(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    assert settle(ref, "SUCCESS", amount="1000.00") == "SUCCESS"
    assert settle(ref, "SUCCESS", amount="1000.00") == "DUPLICATE_SUCCESS"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("1000.00")
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1


async def test_concurrent_identical_webhooks_apply_once(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    body, headers = hook(ref, "SUCCESS", amount="1000.00", event_id="evt-race")

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: post_hook(body, headers).json()["outcome"], range(8)))
    assert outcomes.count("SUCCESS") == 1 and outcomes.count("DUPLICATE") == 7
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("1000.00")
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1


async def test_concurrent_distinct_events_for_one_payment_apply_once(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    calls = [hook(ref, "SUCCESS", amount="1000.00") for _ in range(8)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda c: post_hook(*c).json()["outcome"], calls))
    assert outcomes.count("SUCCESS") == 1 and outcomes.count("DUPLICATE_SUCCESS") == 7
    assert await count(db_session, RepaymentAllocation) == 1
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("1000.00")
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1


async def test_concurrent_payments_never_overfill_an_installment(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch, count=1)
    refs = []
    for _ in range(3):  # three payments, each individually valid at creation
        _, ref = await started(world, r, "5000.00", db_session)
        refs.append(ref)
    calls = [hook(ref, "SUCCESS", amount="5000.00") for ref in refs]
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda c: post_hook(*c).json()["outcome"], calls))
    assert outcomes == ["SUCCESS"] * 3

    (only,) = await installments(db_session, r.schedule_id)
    assert only.principal_paid == only.principal_due == D("5000.00")  # never above what is due
    rows = (await db_session.execute(select(RepaymentPayment))).scalars().all()
    applied = sum(p.principal_applied for p in rows)
    unapplied = sum(p.unapplied_amount for p in rows)
    assert applied == D("5000.00") and unapplied == D("10000.00")  # excess is recorded, not lost
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.BANK].debit_total == D("15000.00")  # three receipts in
    assert balances[L.BANK].credit_total == D("5000.00")  # the one disbursement out
    assert balances[L.UNAPPLIED_RECEIPTS].balance == D("10000.00")
    assert balances[L.LOAN_PRINCIPAL].balance == 0
    assert "REPAYMENT_UNAPPLIED_RECEIPT" in await audit_actions(db_session)
    trial = client.get("/api/v1/admin/ledger/trial-balance", headers=r.finance_headers).json()
    assert trial["balanced"] is True


async def test_concurrent_success_and_reversal_for_different_payments_stay_consistent(
    world, db_session, monkeypatch
):
    r = await active_loan(world, db_session, monkeypatch, count=2)
    _, ref_a = await started(world, r, "2500.00", db_session)
    _, ref_b = await started(world, r, "2500.00", db_session)
    assert settle(ref_a, "SUCCESS", amount="2500.00") == "SUCCESS"
    calls = [hook(ref_a, "REVERSED", amount="2500.00"), hook(ref_b, "SUCCESS", amount="2500.00")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda c: post_hook(*c).json()["outcome"], calls))
    assert outcomes == ["REVERSED", "SUCCESS"]
    stored = await installments(db_session, r.schedule_id)
    assert sum(i.principal_paid for i in stored) == D("2500.00")  # only B remains
    assert all(i.principal_paid <= i.principal_due for i in stored)
    ledger = build_ledger_service(db_session)
    assert await ledger.principal_outstanding(r.offer_id) == D("2500.00")
    assert sum(i.principal_due - i.principal_paid for i in stored) == D("2500.00")


# ======================================================================
# Failure, review, reversal
# ======================================================================


async def test_failed_payment_changes_nothing_and_can_be_retried_with_a_new_key(
    world, db_session, monkeypatch
):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    assert settle(ref, "FAILED", failure_code="INSUFFICIENT_FUNDS") == "FAILED"
    p = await row(db_session, pid)
    assert p.status == "FAILED" and p.failure_code == "INSUFFICIENT_FUNDS" and p.completed_at is None
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0
    assert await count(db_session, RepaymentAllocation) == 0
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 0
    customer_view = client.get(
        f"/api/v1/loan-offers/{r.offer_id}/repayments/{pid}", headers=world.customer_headers
    ).json()
    assert customer_view["status"] == "FAILED" and customer_view["checkout_url"] is None

    assert pay(world, r, "1000.00").status_code == 201  # try again with a fresh key
    assert settle(ref, "FAILED") == "IGNORED_AFTER_FAILURE"


async def test_unknown_failure_codes_are_normalised(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "10.00", db_session)
    settle(ref, "FAILED", failure_code="<script>weird</script>")
    assert (await row(db_session, pid)).failure_code == "PROVIDER_FAILED"


async def test_provider_declining_at_creation_fails_the_payment_cleanly(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    Pay.behaviour = "reject"
    response = pay(world, r, "100.00")
    assert response.status_code == 201 and response.json()["status"] == "FAILED"
    assert Pay.transactions == {}


async def test_success_after_failure_is_never_trusted_automatically(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "FAILED")
    assert settle(ref, "SUCCESS", amount="1000.00") == "LATE_SUCCESS_AFTER_FAILURE"
    p = await row(db_session, pid)
    assert p.status == "REQUIRES_REVIEW" and p.review_reason == "LATE_SUCCESS_AFTER_FAILURE"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 0
    # The customer is told only that it is being processed.
    mine = client.get(f"/api/v1/loan-offers/{r.offer_id}/repayments/{pid}", headers=world.customer_headers).json()
    assert mine["status"] == "PROCESSING"
    assert "REPAYMENT_REQUIRES_REVIEW" in await audit_actions(db_session, pid)
    # Further callbacks do not move it: only an admin recheck against the provider can.
    assert settle(ref, "SUCCESS", amount="1000.00") == "IGNORED_IN_REVIEW"


async def test_amount_mismatch_goes_to_review_without_applying_anything(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    assert settle(ref, "SUCCESS", amount="999.00") == "AMOUNT_MISMATCH"
    p = await row(db_session, pid)
    assert p.status == "REQUIRES_REVIEW" and p.review_reason == "AMOUNT_MISMATCH"
    assert await count(db_session, RepaymentAllocation) == 0


async def test_reference_mismatch_goes_to_review(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    body, headers = hook(
        "dev-pay-other", "SUCCESS", amount="1000.00", idempotency_key=(await row(db_session, pid)).idempotency_key
    )
    assert post_hook(body, headers).json()["outcome"] == "PROVIDER_REF_MISMATCH"
    assert (await row(db_session, pid)).status == "REQUIRES_REVIEW"


async def test_reversal_undoes_exactly_that_payment_and_mirrors_the_ledger(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid_a, ref_a = await started(world, r, "2500.00", db_session)
    pid_b, ref_b = await started(world, r, "1000.00", db_session)
    settle(ref_a, "SUCCESS", amount="2500.00")
    settle(ref_b, "SUCCESS", amount="1000.00")
    first, second = await installments(db_session, r.schedule_id)
    assert (first.principal_paid, second.principal_paid) == (D("2500.00"), D("1000.00"))

    assert settle(ref_b, "REVERSED", amount="1000.00") == "REVERSED"
    first, second = await installments(db_session, r.schedule_id)
    assert (first.status, first.principal_paid) == ("PAID", D("2500.00"))  # untouched
    assert (second.status, second.principal_paid) == ("SCHEDULED", D("0.00"))  # restored
    p = await row(db_session, pid_b)
    assert p.status == "REVERSED" and p.reversed_at is not None
    ledger = build_ledger_service(db_session)
    assert await ledger.principal_outstanding(r.offer_id) == D("2500.00")
    kinds = sorted((await db_session.execute(select(LedgerTransaction.kind))).scalars().all())
    assert kinds == ["DISBURSEMENT", "REPAYMENT", "REPAYMENT", "REPAYMENT_REVERSAL"]
    assert "REPAYMENT_REVERSED" in await audit_actions(db_session, pid_b)
    # Allocation history is kept (append-only); it is the reversal that nets it out.
    assert await count(db_session, RepaymentAllocation) == 2
    mine = client.get(f"/api/v1/loan-offers/{r.offer_id}/repayments/{pid_b}", headers=world.customer_headers).json()
    assert mine["status"] == "REVERSED"


async def test_duplicate_reversal_events_reverse_once(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "SUCCESS", amount="1000.00")
    body, headers = hook(ref, "REVERSED", amount="1000.00", event_id="rev-evt")
    assert post_hook(body, headers).json()["outcome"] == "REVERSED"
    assert post_hook(body, headers).json()["outcome"] == "DUPLICATE"
    assert settle(ref, "REVERSED", amount="1000.00") == "IGNORED_TERMINAL"
    assert settle(ref, "SUCCESS", amount="1000.00") == "IGNORED_TERMINAL"  # cannot come back
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT_REVERSAL") == 1


async def test_reversal_reported_in_one_step_books_both_legs(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    assert settle(ref, "REVERSED", amount="1000.00") == "REVERSED"
    assert (await row(db_session, pid)).status == "REVERSED"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0
    kinds = sorted((await db_session.execute(select(LedgerTransaction.kind))).scalars().all())
    assert kinds == ["DISBURSEMENT", "REPAYMENT", "REPAYMENT_REVERSAL"]


async def test_reversing_a_payment_with_unapplied_money_nets_the_liability_out(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch, count=1)
    _, ref_a = await started(world, r, "5000.00", db_session)
    _, ref_b = await started(world, r, "5000.00", db_session)
    settle(ref_a, "SUCCESS", amount="5000.00")
    settle(ref_b, "SUCCESS", amount="5000.00")  # all of it unapplied
    assert settle(ref_b, "REVERSED", amount="5000.00") == "REVERSED"
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.UNAPPLIED_RECEIPTS].balance == 0
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("5000.00")


async def test_ledger_failure_rolls_the_whole_payment_back(world, db_session, monkeypatch):
    from app.services.ledger import LedgerService

    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)

    async def boom(self, **kw):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(LedgerService, "post_repayment", boom)
    body, headers = hook(ref, "SUCCESS", amount="1000.00")
    with pytest.raises(RuntimeError):
        post_hook(body, headers)
    p = await row(db_session, pid)
    assert p.status == "PENDING" and p.completed_at is None
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0
    assert await count(db_session, RepaymentAllocation) == 0
    assert await count(db_session, RepaymentEvent) == 0  # so the provider's retry is not seen as a duplicate


# ======================================================================
# Provider outage, polling, reconciliation
# ======================================================================


async def test_provider_outage_at_start_is_recoverable(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    Pay.behaviour = "down"
    response = pay(world, r, "1000.00")
    assert response.status_code == 201 and response.json()["status"] == "PROCESSING"
    pid = response.json()["id"]
    p = await row(db_session, pid)
    assert p.status == "INITIATED" and p.provider_ref is None  # recorded, not lost

    Pay.behaviour = "ok"
    fast_forward(monkeypatch, minutes=2)
    stats = await run_repayments()
    assert stats["dispatched"] == 1 and stats["errors"] == 0
    p = await row(db_session, pid)
    assert p.status == "PENDING" and p.provider_ref
    assert len(Pay.transactions) == 1


async def test_timeout_after_the_provider_created_it_never_double_collects(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    Pay.behaviour = "timeout_after"  # provider has it; we never saw the answer
    pid = pay(world, r, "1000.00").json()["id"]
    assert (await row(db_session, pid)).status == "INITIATED"
    assert len(Pay.transactions) == 1

    Pay.behaviour = "ok"
    fast_forward(monkeypatch, minutes=2)
    await run_repayments()
    await run_repayments()  # a second worker pass is harmless
    assert (await row(db_session, pid)).status == "PENDING"
    assert len(Pay.transactions) == 1 and Pay.create_calls.count((await row(db_session, pid)).idempotency_key) >= 2


async def test_timeout_before_creation_is_retried_then_created_once(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    Pay.behaviour = "timeout_before"
    pid = pay(world, r, "1000.00").json()["id"]
    assert Pay.transactions == {}
    Pay.behaviour = "ok"
    fast_forward(monkeypatch, minutes=2)
    await run_repayments()
    assert (await row(db_session, pid)).status == "PENDING" and len(Pay.transactions) == 1


async def test_a_result_that_was_lost_is_found_through_the_idempotency_key_in_a_callback(
    world, db_session, monkeypatch
):
    r = await active_loan(world, db_session, monkeypatch)
    Pay.behaviour = "timeout_after"
    pid = pay(world, r, "1000.00").json()["id"]
    p = await row(db_session, pid)
    assert p.status == "INITIATED" and p.provider_ref is None
    ref = Pay.ref_for(p.idempotency_key)
    body, headers = hook(ref, "SUCCESS", amount="1000.00", idempotency_key=p.idempotency_key)
    assert post_hook(body, headers).json()["outcome"] == "SUCCESS"
    p = await row(db_session, pid)
    assert p.status == "SUCCESS" and p.provider_ref == ref


async def test_polling_fallback_settles_a_payment_whose_webhook_never_came(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    key = (await row(db_session, pid)).idempotency_key
    assert (await run_repayments())["reconciled"] == 0  # too fresh to poll
    Pay.transactions[key]["status"] = "SUCCESS"  # customer paid; webhook was lost
    fast_forward(monkeypatch, minutes=11)
    stats = await run_repayments()
    assert stats["reconciled"] == 1 and stats["errors"] == 0
    assert (await row(db_session, pid)).status == "SUCCESS"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("1000.00")
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1
    await run_repayments()  # repeating changes nothing
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1


async def test_polling_records_an_expired_or_failed_payment(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    key = (await row(db_session, pid)).idempotency_key
    Pay.transactions[key].update(status="FAILED", failure_code="EXPIRED")
    fast_forward(monkeypatch, minutes=11)
    await run_repayments()
    p = await row(db_session, pid)
    assert p.status == "FAILED" and p.failure_code == "EXPIRED"


async def test_polling_a_payment_the_provider_does_not_know_goes_to_review(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    Pay.transactions.clear()
    fast_forward(monkeypatch, minutes=11)
    await run_repayments()
    p = await row(db_session, pid)
    assert p.status == "REQUIRES_REVIEW" and p.review_reason == "PROVIDER_REF_NOT_FOUND"


async def test_unresolved_for_too_long_goes_to_review(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    fast_forward(monkeypatch, hours=25)
    await run_repayments()
    p = await row(db_session, pid)
    assert p.status == "REQUIRES_REVIEW" and p.review_reason == "UNRESOLVED_TOO_LONG"


async def test_provider_down_during_polling_is_survivable(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    Pay.behaviour = "down"
    fast_forward(monkeypatch, minutes=11)
    stats = await run_repayments()
    assert stats["errors"] == 0
    assert (await row(db_session, pid)).status == "PENDING"  # unknown is not failure


# ======================================================================
# Admin recheck (permission-controlled, audited)
# ======================================================================


async def test_recheck_settles_from_the_providers_record_and_is_audited(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    key = (await row(db_session, pid)).idempotency_key
    Pay.transactions[key]["status"] = "SUCCESS"
    response = client.post(f"/api/v1/admin/repayments/payments/{pid}/recheck", headers=r.finance_headers)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "SUCCESS" and response.json()["payment"]["status"] == "SUCCESS"
    assert "REPAYMENT_RECHECKED" in await audit_actions(db_session, pid)
    again = client.post(f"/api/v1/admin/repayments/payments/{pid}/recheck", headers=r.finance_headers)
    assert again.status_code == 409  # already resolved


async def test_recheck_moves_a_review_case_only_on_provider_evidence(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "FAILED")
    settle(ref, "SUCCESS", amount="1000.00")  # -> REQUIRES_REVIEW
    url = f"/api/v1/admin/repayments/payments/{pid}/recheck"
    key = (await row(db_session, pid)).idempotency_key
    # Provider still says FAILED: the case resolves as failed, nothing applied.
    Pay.transactions[key]["status"] = "FAILED"
    assert client.post(url, headers=r.finance_headers).json()["payment"]["status"] == "FAILED"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == 0


async def test_recheck_with_provider_confirmation_resolves_review_to_success(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "FAILED")
    settle(ref, "SUCCESS", amount="1000.00")
    key = (await row(db_session, pid)).idempotency_key
    Pay.transactions[key]["status"] = "SUCCESS"
    response = client.post(f"/api/v1/admin/repayments/payments/{pid}/recheck", headers=r.finance_headers)
    assert response.json()["payment"]["status"] == "SUCCESS"
    assert (await installments(db_session, r.schedule_id))[0].principal_paid == D("1000.00")
    assert await count(db_session, LedgerTransaction, LedgerTransaction.kind == "REPAYMENT") == 1


async def test_recheck_when_the_provider_is_down_changes_nothing(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    Pay.behaviour = "down"
    response = client.post(f"/api/v1/admin/repayments/payments/{pid}/recheck", headers=r.finance_headers)
    assert response.status_code == 503 and response.headers.get("retry-after")
    assert (await row(db_session, pid)).status == "PENDING"


async def test_recheck_requires_the_review_permission(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, _ = await started(world, r, "1000.00", db_session)
    auditor, auditor_headers = await make_actor(monkeypatch, db_session, role="AUDITOR")
    url = f"/api/v1/admin/repayments/payments/{pid}/recheck"
    assert client.post(url, headers=auditor_headers).status_code == 403
    assert client.post(url, headers=world.admin_headers).status_code == 403
    assert client.post(url, headers=world.customer_headers).status_code == 403
    assert "REPAYMENT_RECHECKED" not in await audit_actions(db_session, pid)


async def test_admin_payment_reads_are_role_restricted_and_show_events(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "SUCCESS", amount="1000.00")
    auditor, auditor_headers = await make_actor(monkeypatch, db_session, role="AUDITOR")
    detail = client.get(f"/api/v1/admin/repayments/payments/{pid}", headers=auditor_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "SUCCESS" and body["events"][0]["outcome"] == "SUCCESS"
    assert body["principal_applied"] == "1000.00"
    listed = client.get(
        f"/api/v1/admin/repayments/payments?status=SUCCESS&loan_offer_id={r.offer_id}", headers=auditor_headers
    )
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert client.get("/api/v1/admin/repayments/payments", headers=world.admin_headers).status_code == 403
    assert client.get("/api/v1/admin/repayments/payments", headers=world.customer_headers).status_code == 403


# ======================================================================
# Database-level protection of payment history
# ======================================================================


@pytest.mark.parametrize(
    "sql,fragment",
    [
        ("UPDATE repayment_payments SET amount = amount + 1", "immutable"),
        ("UPDATE repayment_payments SET idempotency_key = 'other'", "immutable"),
        ("UPDATE repayment_payments SET provider_ref = 'other'", "immutable"),
        ("DELETE FROM repayment_payments", "cannot be deleted"),
        ("UPDATE repayment_payment_allocations SET principal_amount = 1", "append-only"),
        ("DELETE FROM repayment_payment_allocations", "append-only"),
    ],
)
async def test_payment_history_is_protected_by_the_database(world, db_session, monkeypatch, sql, fragment):
    r = await active_loan(world, db_session, monkeypatch)
    _, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "SUCCESS", amount="1000.00")
    with pytest.raises(DBAPIError, match=fragment):
        await db_session.execute(text(sql))
    await db_session.rollback()


async def test_a_successful_payment_can_only_be_reversed_and_a_reversed_one_is_frozen(
    world, db_session, monkeypatch
):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "SUCCESS", amount="1000.00")
    for sql in (
        "UPDATE repayment_payments SET status = 'FAILED'",
        "UPDATE repayment_payments SET status = 'PENDING'",
        "UPDATE repayment_payments SET principal_applied = 1, unapplied_amount = 999",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()
    settle(ref, "REVERSED", amount="1000.00")
    with pytest.raises(DBAPIError, match="reversed payment is immutable"):
        await db_session.execute(text("UPDATE repayment_payments SET review_reason = 'x'"))
    await db_session.rollback()


async def test_audit_trail_has_no_secrets_or_account_numbers(world, db_session, monkeypatch):
    r = await active_loan(world, db_session, monkeypatch)
    pid, ref = await started(world, r, "1000.00", db_session)
    settle(ref, "SUCCESS", amount="1000.00")
    rows = await db_session.execute(
        select(AuditLog.event_metadata, AuditLog.new_value, AuditLog.old_value, AuditLog.reason).where(
            AuditLog.entity_type.in_(["repayment_payment", "repayment_schedule"])
        )
    )
    blob = json.dumps([list(x) for x in rows], default=str)
    for secret in (SECRET, NUMBER, "https://pay.dev.invalid"):
        assert secret not in blob
    actions = set(await audit_actions(db_session))
    assert {"REPAYMENT_INITIATED", "REPAYMENT_PENDING", "REPAYMENT_SUCCESS"} <= actions
