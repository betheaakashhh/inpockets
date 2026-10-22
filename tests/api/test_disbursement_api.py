"""End-to-end 2.11 disbursement tests on real Postgres with the dev providers."""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import get_settings
from app.domain import disbursement as dom
from app.main import app
from app.models.audit_log import AuditLog
from app.models.disbursement import Disbursement, DisbursementEvent
from app.models.user_profile import UserProfile
from app.providers.bank_verification_development import (
    DevelopmentBankVerificationProvider as DevBank,
)
from app.providers.disbursement_development import (
    DevelopmentDisbursementProvider as Dev,
    sign_webhook,
)
from app.providers.esign_development import DevelopmentESignProvider as DevESign
from app.services.disbursement_factory import build_disbursement_service
from app.workers.disbursement import run_once
from tests.api.test_bank_verification_api import FP, IFSC, K1, K2, acct
from tests.api.test_bank_verification_api import verify as verify_bank
from tests.api.test_esign_api import (
    SIGNED_PDF,  # noqa: F401
    accepted_offer,
    callback as esign_callback,
    load_tx,
    post_callback as post_esign_callback,
    start as start_esign,
)
from tests.api.test_loan_offer_api import issued_offer, make_actor as _make_actor, world  # noqa: F401

client = TestClient(app)
SECRET = "disbursement-test-secret"
ESIGN_SECRET = "unit-test-webhook-secret"
NUMBER = acct("6789")
AMOUNT = "5000.00"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "disbursement_webhook_secret", SECRET)
    monkeypatch.setattr(s, "esign_webhook_secret", ESIGN_SECRET)
    monkeypatch.setattr(s, "esign_require_signed_artifact", True)
    monkeypatch.setattr(s, "field_encryption_keys", f"k1:{K1},k2:{K2}")
    monkeypatch.setattr(s, "field_encryption_active_key_id", "k1")
    monkeypatch.setattr(s, "bank_fingerprint_key", FP)
    monkeypatch.setattr(s, "rate_limit_sensitive_per_minute", 1000)
    monkeypatch.setattr(s, "rate_limit_user_per_minute", 1000)
    for p in (Dev, DevESign, DevBank):
        p.reset()
    yield
    for p in (Dev, DevESign, DevBank):
        p.reset()


# ------------------------------------------------------------------ helpers


async def make_actor(monkeypatch, db_session, *, role=None):
    row, headers = await _make_actor(monkeypatch, db_session, role=role)
    return SimpleNamespace(id=row.id), headers


async def ready(world, db_session, monkeypatch, *, bank=True, sign=True):
    """Accepted offer, e-signed, customer bank-verified, FINANCE admin."""
    customer_id = world.customer.id
    offer = await accepted_offer(world)
    if sign:
        assert start_esign(offer["id"], world.customer_headers).status_code == 200
        tx = await load_tx(db_session, offer["id"])
        body, headers = esign_callback(tx.provider_ref, "SIGNED", tx.document_checksum)
        assert post_esign_callback(body, headers).json()["outcome"] == "SIGNED"
    if bank:
        db_session.add(UserProfile(user_id=customer_id, first_name="Asha", last_name="Rao"))
        await db_session.commit()
        response = verify_bank(world.customer_headers, NUMBER)
        assert response.json()["status"] == "VERIFIED", response.text
    finance, finance_headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    return SimpleNamespace(
        offer_id=offer["id"],
        customer_id=customer_id,
        finance=finance,
        finance_headers=finance_headers,
    )


def create(headers, offer_id):
    return client.post(
        "/api/v1/admin/disbursements", json={"loan_offer_id": offer_id}, headers=headers
    )


async def current(db_session, offer_id) -> Disbursement:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(Disbursement)
            .where(Disbursement.loan_offer_id == offer_id)
            .order_by(Disbursement.attempt.desc())
        )
    ).scalars().first()


async def all_rows(db_session, offer_id):
    db_session.expire_all()
    return (
        await db_session.execute(
            select(Disbursement)
            .where(Disbursement.loan_offer_id == offer_id)
            .order_by(Disbursement.attempt)
        )
    ).scalars().all()


def hook(ref, status, *, amount=AMOUNT, event_id=None, utr=None, secret=SECRET,
         timestamp=None, **extra):
    body = json.dumps(
        {
            "event_id": event_id or f"evt-{uuid4()}",
            "provider_ref": ref,
            "status": status,
            "amount": amount,
            "utr": utr,
            "occurred_at": dom.utcnow().isoformat(),
            **extra,
        }
    ).encode()
    headers = sign_webhook(secret, body, timestamp) if secret else {}
    headers["Content-Type"] = "application/json"
    return body, headers


def post_hook(body, headers, provider="development"):
    return client.post(f"/api/v1/webhooks/disbursement/{provider}", content=body, headers=headers)


async def dispatched(world, db_session, monkeypatch, behaviour="ok"):
    """Ready world with a disbursement claimed and sent to the provider."""
    r = await ready(world, db_session, monkeypatch)
    Dev.behaviour = behaviour
    assert create(r.finance_headers, r.offer_id).status_code == 201
    await run_once()
    return r, await current(db_session, r.offer_id)


def customer_view(world, offer_id):
    return client.get(f"/api/v1/loan-offers/{offer_id}/disbursement", headers=world.customer_headers)


def fast_forward(monkeypatch, **delta):
    real = dom.utcnow
    monkeypatch.setattr(dom, "utcnow", lambda: real() + timedelta(**delta))


async def audit_actions(db_session, entity_id=None):
    stmt = select(AuditLog.action)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == str(entity_id))
    return [r[0] for r in await db_session.execute(stmt)]


async def audit_blob(db_session) -> str:
    rows = await db_session.execute(
        select(AuditLog.event_metadata, AuditLog.new_value, AuditLog.old_value, AuditLog.reason)
    )
    return json.dumps([list(r) for r in rows], default=str)


# ----------------------------------------------------------------- creation


async def test_create_records_pending_bound_to_stored_terms(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    response = create(r.finance_headers, r.offer_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING" and body["amount"] == AMOUNT and body["currency"] == "INR"
    assert body["account_number_masked"] == "XXXXXXXX6789" and body["attempt"] == 1
    assert NUMBER not in response.text
    d = await current(db_session, r.offer_id)
    assert d.idempotency_key == f"inp-disb-{r.offer_id}-a1"
    assert d.provider_ref is None and d.dispatch_attempts == 0
    assert "DISBURSEMENT_CREATED" in await audit_actions(db_session, d.id)


async def test_create_is_idempotent_per_offer(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    first = create(r.finance_headers, r.offer_id).json()
    second = create(r.finance_headers, r.offer_id).json()
    assert first["id"] == second["id"]
    assert len(await all_rows(db_session, r.offer_id)) == 1


async def test_create_requires_the_whole_chain(world, db_session, monkeypatch):
    # Offer issued but not accepted.
    offer = await issued_offer(world)
    finance, headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    assert create(headers, offer["id"]).status_code == 409
    assert create(headers, str(uuid4())).status_code == 404


async def test_create_refused_without_signature_or_bank(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch, sign=False, bank=False)
    assert create(r.finance_headers, r.offer_id).status_code == 409  # not e-signed
    r2_world = world
    # Sign but still no bank account.
    assert start_esign(r.offer_id, r2_world.customer_headers).status_code == 200
    tx = await load_tx(db_session, r.offer_id)
    body, headers = esign_callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    post_esign_callback(body, headers)
    refused = create(r.finance_headers, r.offer_id)
    assert refused.status_code == 409 and "bank" in refused.json()["detail"].lower()
    assert await all_rows(db_session, r.offer_id) == []


async def test_amount_cannot_be_chosen_by_the_caller(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    response = client.post(
        "/api/v1/admin/disbursements",
        json={"loan_offer_id": r.offer_id, "amount": "999999.00"},
        headers=r.finance_headers,
    )
    assert response.status_code == 422
    assert await all_rows(db_session, r.offer_id) == []


# --------------------------------------------------------------- happy paths


async def test_instant_success_through_the_worker(world, db_session, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    r = await ready(world, db_session, monkeypatch)
    Dev.behaviour = "instant"
    create(r.finance_headers, r.offer_id)
    stats = await run_once()
    assert stats["claimed"] == 1 and stats["submitted"] == 1 and stats["errors"] == 0

    d = await current(db_session, r.offer_id)
    assert d.status == "SUCCESS" and d.utr and d.provider_ref.startswith("dev-disb-")
    assert d.completed_at is not None and d.dispatch_attempts == 1
    assert len(Dev.transactions) == 1
    ledger = Dev.transactions[d.idempotency_key]
    assert str(ledger["amount"]) == AMOUNT and ledger["beneficiary_last4"] == "6789"

    view = customer_view(world, r.offer_id).json()
    assert view["status"] == "DISBURSED" and view["utr"] == d.utr
    assert view["account_number_masked"] == "XXXXXXXX6789"
    assert NUMBER not in caplog.text and NUMBER not in await audit_blob(db_session)

    actions = await audit_actions(db_session)
    assert "BANK_ACCOUNT_DECRYPTED" in actions
    assert {"DISBURSEMENT_PROCESSING", "DISBURSEMENT_SUCCESS"} <= set(
        await audit_actions(db_session, d.id)
    )


async def test_async_success_arrives_by_signed_webhook_only(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    assert d.status == "PROCESSING" and d.provider_ref
    # Still processing from the customer's point of view.
    assert customer_view(world, r.offer_id).json()["status"] == "PROCESSING"
    assert customer_view(world, r.offer_id).json()["utr"] is None

    body, headers = hook(d.provider_ref, "SUCCESS", utr="UTR123456")
    response = post_hook(body, headers)
    assert response.status_code == 200 and response.json()["outcome"] == "SUCCESS"
    d = await current(db_session, r.offer_id)
    assert d.status == "SUCCESS" and d.utr == "UTR123456"
    assert customer_view(world, r.offer_id).json()["status"] == "DISBURSED"


# --------------------------------------------------- never trust client success


async def test_customers_cannot_report_trigger_or_confirm_a_payout(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    url = f"/api/v1/loan-offers/{r.offer_id}/disbursement"
    for method in ("post", "put", "patch", "delete"):
        response = client.request(
            method.upper(), url, json={"status": "SUCCESS", "utr": "FAKE"},
            headers=world.customer_headers,
        )
        assert response.status_code in (404, 405), method
    assert create(world.customer_headers, r.offer_id).status_code in (401, 403)
    assert (await current(db_session, r.offer_id)).status == "PROCESSING"


async def test_unsigned_or_forged_webhooks_change_nothing(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    good_body, good_headers = hook(d.provider_ref, "SUCCESS", utr="X")
    candidates = [
        hook(d.provider_ref, "SUCCESS", secret="wrong"),
        (good_body, {"Content-Type": "application/json"}),
        hook(d.provider_ref, "SUCCESS", timestamp=1),
        (good_body.replace(b"SUCCESS", b"FAILED"), good_headers),
        (good_body, {**good_headers, "X-Disbursement-Timestamp": "nope"}),
    ]
    for body, headers in candidates:
        assert post_hook(body, headers).status_code == 401
    assert (await current(db_session, r.offer_id)).status == "PROCESSING"
    assert (
        await db_session.execute(select(func.count()).select_from(DisbursementEvent))
    ).scalar_one() == 0


async def test_webhooks_rejected_when_secret_unset(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "SUCCESS")
    monkeypatch.setattr(get_settings(), "disbursement_webhook_secret", None)
    assert post_hook(body, headers).status_code == 401


async def test_webhook_unknown_provider_malformed_and_unknown_reference(
    world, db_session, monkeypatch
):
    body, headers = hook("dev-disb-unknown", "SUCCESS")
    assert post_hook(body, headers).status_code == 404
    assert post_hook(body, headers, provider="acme").status_code == 404
    junk = b"not json"
    junk_headers = sign_webhook(SECRET, junk)
    assert post_hook(junk, junk_headers).status_code == 400
    odd = json.dumps({"event_id": "e", "provider_ref": "r", "status": "WEIRD"}).encode()
    assert post_hook(odd, sign_webhook(SECRET, odd)).status_code == 400
    assert (
        await db_session.execute(select(func.count()).select_from(DisbursementEvent))
    ).scalar_one() == 0


async def test_amount_mismatch_goes_to_review_never_success(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "SUCCESS", amount="1.00", utr="U")
    assert post_hook(body, headers).json()["outcome"] == "AMOUNT_MISMATCH"
    d = await current(db_session, r.offer_id)
    assert d.status == "REQUIRES_REVIEW" and d.review_reason == "AMOUNT_MISMATCH"
    assert d.utr is None
    # Customers just see "processing".
    assert customer_view(world, r.offer_id).json()["status"] == "PROCESSING"


# ----------------------------------------------------------------- failures


@pytest.mark.parametrize(
    "behaviour,code", [("fail", "BANK_DECLINED"), ("reject", "INVALID_BENEFICIARY")]
)
async def test_provider_failures_mark_failed(world, db_session, monkeypatch, behaviour, code):
    r, d = await dispatched(world, db_session, monkeypatch, behaviour)
    assert d.status == "FAILED" and d.failure_code == code
    assert customer_view(world, r.offer_id).json()["status"] == "FAILED"


async def test_failed_webhook_marks_failed(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "FAILED", failure_code="INSUFFICIENT_FUNDS")
    assert post_hook(body, headers).json()["outcome"] == "FAILED"
    d = await current(db_session, r.offer_id)
    assert d.status == "FAILED" and d.failure_code == "INSUFFICIENT_FUNDS"


async def test_unknown_provider_failure_code_is_normalised(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "FAILED", failure_code="free text from provider 42")
    post_hook(body, headers)
    assert (await current(db_session, r.offer_id)).failure_code == "PROVIDER_FAILED"


# ------------------------------------------------- timeout / unknown status


async def test_timeout_after_payout_is_reconciled_without_paying_twice(
    world, db_session, monkeypatch
):
    r, d = await dispatched(world, db_session, monkeypatch, "timeout_after")
    # Unknown: we do not know a payout exists, and we do NOT mark it failed.
    assert d.status == "PROCESSING" and d.provider_ref is None
    assert len(Dev.transactions) == 1  # the provider did create it

    # Within the grace period nothing is re-sent.
    Dev.behaviour = "ok"
    stats = await run_once()
    assert stats["reconciled"] == 0 and len(Dev.submit_calls) == 1

    fast_forward(monkeypatch, minutes=30)
    stats = await run_once()
    assert stats["reconciled"] == 1
    d = await current(db_session, r.offer_id)
    assert d.status == "PROCESSING" and d.provider_ref == Dev.ref_for(d.idempotency_key)
    assert len(Dev.transactions) == 1  # still exactly one payout

    Dev.transactions[d.idempotency_key].update(status="SUCCESS", utr="UTR999")
    fast_forward(monkeypatch, minutes=60)
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "SUCCESS" and d.utr == "UTR999"
    assert len(Dev.transactions) == 1


async def test_timeout_before_payout_resubmits_safely_after_grace(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "timeout_before")
    assert d.status == "PROCESSING" and Dev.transactions == {}
    Dev.behaviour = "ok"
    fast_forward(monkeypatch, minutes=30)
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "PROCESSING" and d.provider_ref is not None
    assert len(Dev.transactions) == 1 and d.dispatch_attempts == 2


async def test_provider_outage_is_recoverable_then_escalates(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "down")
    assert d.status == "PROCESSING"
    fast_forward(monkeypatch, minutes=30)
    await run_once()  # still down: stays unknown
    assert (await current(db_session, r.offer_id)).status == "PROCESSING"

    Dev.behaviour = "ok"  # provider recovers
    fast_forward(monkeypatch, minutes=60)
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "PROCESSING" and d.provider_ref and len(Dev.transactions) == 1


async def test_outage_beyond_limit_requires_review(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "down")
    fast_forward(monkeypatch, hours=48)
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "REQUIRES_REVIEW" and d.review_reason == "PROVIDER_UNRESOLVED"


async def test_stuck_processing_with_ref_goes_to_review_when_too_old(
    world, db_session, monkeypatch
):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    fast_forward(monkeypatch, hours=48)
    await run_once()  # provider still says PROCESSING after 48h
    d = await current(db_session, r.offer_id)
    assert d.status == "REQUIRES_REVIEW" and d.review_reason == "UNRESOLVED_TOO_LONG"


async def test_polling_fallback_resolves_a_missed_webhook(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    Dev.transactions[d.idempotency_key].update(status="SUCCESS", utr="UTRPOLL")
    fast_forward(monkeypatch, minutes=30)
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "SUCCESS" and d.utr == "UTRPOLL" and d.last_polled_at is not None


# ------------------------------------------------ duplicate workers / creation


async def test_duplicate_worker_execution_is_harmless(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    Dev.behaviour = "instant"
    create(r.finance_headers, r.offer_id)
    results = await asyncio.gather(run_once(), run_once(), run_once(), run_once())
    assert sum(s["claimed"] for s in results) == 1
    assert len(Dev.submit_calls) == 1 and len(Dev.transactions) == 1
    d = await current(db_session, r.offer_id)
    assert d.status == "SUCCESS" and d.dispatch_attempts == 1


async def test_submitting_a_claimed_row_twice_never_resends(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    did = d.id
    service = build_disbursement_service(db_session)
    assert await service.submit_claimed(did) == "SKIPPED"
    await db_session.commit()
    assert len(Dev.submit_calls) == 1


async def test_concurrent_duplicate_disbursement_requests_create_one(
    world, db_session, monkeypatch
):
    r = await ready(world, db_session, monkeypatch)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: create(r.finance_headers, r.offer_id), range(6)))
    assert {x.status_code for x in responses} == {201}
    assert len({x.json()["id"] for x in responses}) == 1
    assert len(await all_rows(db_session, r.offer_id)) == 1
    Dev.behaviour = "instant"
    await asyncio.gather(run_once(), run_once())
    assert len(Dev.transactions) == 1


async def test_database_allows_one_live_disbursement_per_offer(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    create(r.finance_headers, r.offer_id)
    d = await current(db_session, r.offer_id)
    db_session.add(
        Disbursement(
            user_id=d.user_id, loan_application_id=d.loan_application_id,
            loan_offer_id=d.loan_offer_id, loan_offer_version=d.loan_offer_version,
            esign_transaction_id=d.esign_transaction_id,
            bank_verification_id=d.bank_verification_id, amount=d.amount, currency="INR",
            beneficiary_last4="6789", beneficiary_ifsc=d.beneficiary_ifsc, status="PENDING",
            attempt=2, idempotency_key="other-key", provider="development",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# --------------------------------------------------- reversal / duplicate hooks


async def test_duplicate_webhook_and_reversal_are_safe(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    success_body, success_headers = hook(d.provider_ref, "SUCCESS", utr="U1", event_id="evt-s")
    assert post_hook(success_body, success_headers).json()["outcome"] == "SUCCESS"
    again = post_hook(success_body, sign_webhook(SECRET, success_body))
    assert again.status_code == 200 and again.json()["outcome"] == "DUPLICATE"
    # Same report under a new event id: no second success.
    other, other_headers = hook(d.provider_ref, "SUCCESS", utr="U1")
    assert post_hook(other, other_headers).json()["outcome"] == "DUPLICATE_SUCCESS"

    rev_body, rev_headers = hook(d.provider_ref, "REVERSED", event_id="evt-r")
    assert post_hook(rev_body, rev_headers).json()["outcome"] == "REVERSED"
    d = await current(db_session, r.offer_id)
    assert d.status == "REVERSED" and d.reversed_at is not None and d.completed_at is not None
    assert customer_view(world, r.offer_id).json()["status"] == "REVERSED"

    dup_rev = post_hook(rev_body, sign_webhook(SECRET, rev_body))
    assert dup_rev.json()["outcome"] == "DUPLICATE"
    new_rev, new_rev_headers = hook(d.provider_ref, "REVERSED")
    assert post_hook(new_rev, new_rev_headers).json()["outcome"] == "IGNORED_TERMINAL"

    actions = await audit_actions(db_session, d.id)
    assert actions.count("DISBURSEMENT_SUCCESS") == 1 and actions.count("DISBURSEMENT_REVERSED") == 1
    events = (
        await db_session.execute(select(func.count()).select_from(DisbursementEvent))
    ).scalar_one()
    assert events == 4  # evt-s, new-id success, evt-r, new-id reversal (dups not stored)


async def test_reversal_reported_while_processing_records_success_then_reversal(
    world, db_session, monkeypatch
):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "REVERSED", utr="U9")
    assert post_hook(body, headers).json()["outcome"] == "REVERSED"
    d = await current(db_session, r.offer_id)
    assert d.status == "REVERSED" and d.utr == "U9"


async def test_conflicting_reports_after_success_are_ignored_and_audited(
    world, db_session, monkeypatch
):
    r, d = await dispatched(world, db_session, monkeypatch, "instant")
    body, headers = hook(d.provider_ref, "FAILED")
    assert post_hook(body, headers).json()["outcome"] == "IGNORED_AFTER_SUCCESS"
    assert (await current(db_session, r.offer_id)).status == "SUCCESS"
    assert "DISBURSEMENT_CONFLICT_IGNORED" in await audit_actions(db_session, d.id)


async def test_late_success_after_failure_requires_review(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "fail")
    body, headers = hook(d.provider_ref, "SUCCESS", utr="LATE")
    assert post_hook(body, headers).json()["outcome"] == "LATE_SUCCESS_AFTER_FAILURE"
    d = await current(db_session, r.offer_id)
    assert d.status == "REQUIRES_REVIEW" and d.utr is None


async def test_callbacks_while_in_review_are_recorded_but_not_applied(
    world, db_session, monkeypatch
):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "SUCCESS", amount="1.00")
    post_hook(body, headers)  # -> review
    body, headers = hook(d.provider_ref, "SUCCESS", utr="U")
    assert post_hook(body, headers).json()["outcome"] == "IGNORED_IN_REVIEW"
    assert (await current(db_session, r.offer_id)).status == "REQUIRES_REVIEW"


# ----------------------------------------------------------- admin recheck


def recheck(headers, did):
    return client.post(f"/api/v1/admin/disbursements/{did}/recheck", headers=headers)


async def review_case(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "SUCCESS", amount="1.00")
    post_hook(body, headers)
    return r, await current(db_session, r.offer_id)


async def test_recheck_resolves_review_only_from_provider_truth(world, db_session, monkeypatch):
    r, d = await review_case(world, db_session, monkeypatch)
    # Provider says still processing: stays in review.
    response = recheck(r.finance_headers, d.id)
    assert response.status_code == 200 and response.json()["disbursement"]["status"] == "REQUIRES_REVIEW"
    # Provider now confirms the right amount paid.
    Dev.transactions[d.idempotency_key].update(status="SUCCESS", utr="UTROK")
    response = recheck(r.finance_headers, d.id)
    assert response.json()["outcome"] == "SUCCESS"
    d = await current(db_session, r.offer_id)
    assert d.status == "SUCCESS" and d.utr == "UTROK" and d.review_reason is None
    assert "DISBURSEMENT_RECHECKED" in await audit_actions(db_session, d.id)


async def test_recheck_with_provider_amount_mismatch_stays_in_review(world, db_session, monkeypatch):
    r, d = await review_case(world, db_session, monkeypatch)
    from decimal import Decimal

    Dev.transactions[d.idempotency_key].update(status="SUCCESS", utr="U", amount=Decimal("1.00"))
    assert recheck(r.finance_headers, d.id).json()["outcome"] == "AMOUNT_MISMATCH"
    assert (await current(db_session, r.offer_id)).status == "REQUIRES_REVIEW"


async def test_recheck_not_found_in_review_fails_the_payout(world, db_session, monkeypatch):
    r, d = await review_case(world, db_session, monkeypatch)
    Dev.transactions.clear()  # provider has no record of the key
    response = recheck(r.finance_headers, d.id)
    assert response.json()["disbursement"]["status"] == "FAILED"
    assert response.json()["disbursement"]["failure_code"] == "PROVIDER_NOT_FOUND"


async def test_recheck_permissions_and_state_rules(world, db_session, monkeypatch):
    r, d = await review_case(world, db_session, monkeypatch)
    for role in ("AUDITOR", "COLLECTIONS_AGENT", "SENIOR_UNDERWRITER", "CUSTOMER_SUPPORT"):
        _, headers = await make_actor(monkeypatch, db_session, role=role)
        assert recheck(headers, d.id).status_code == 403
    assert recheck(world.customer_headers, d.id).status_code in (401, 403)
    assert recheck(r.finance_headers, uuid4()).status_code == 404
    Dev.behaviour = "down"
    assert recheck(r.finance_headers, d.id).status_code == 503
    assert (await current(db_session, r.offer_id)).status == "REQUIRES_REVIEW"
    Dev.behaviour = "ok"
    Dev.transactions[d.idempotency_key].update(status="FAILED", failure_code="BANK_DECLINED")
    assert recheck(r.finance_headers, d.id).status_code == 200
    assert recheck(r.finance_headers, d.id).status_code == 409  # resolved already


# ------------------------------------------------------------ manual retry


def retry(headers, did, reason="Provider confirmed the failure; retrying payout"):
    return client.post(
        f"/api/v1/admin/disbursements/{did}/retry", json={"reason": reason}, headers=headers
    )


async def test_retry_creates_a_new_attempt_with_a_new_key(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "fail")
    old_id, old_key = d.id, d.idempotency_key
    response = retry(r.finance_headers, old_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["attempt"] == 2 and body["status"] == "PENDING"
    assert body["retry_of_id"] == str(old_id) and body["idempotency_key"] != old_key

    Dev.behaviour = "instant"
    await run_once()
    rows = await all_rows(db_session, r.offer_id)
    assert [x.status for x in rows] == ["FAILED", "SUCCESS"]
    assert len(Dev.transactions) == 2  # one failed attempt, one real payout

    log = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "DISBURSEMENT_RETRIED")
        )
    ).scalar_one()
    assert log.reason and log.actor_role == "FINANCE"


async def test_retry_is_permission_controlled(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "fail")
    for role in ("AUDITOR", "COLLECTIONS_AGENT", "SENIOR_UNDERWRITER", "KYC_REVIEWER"):
        _, headers = await make_actor(monkeypatch, db_session, role=role)
        assert retry(headers, d.id).status_code == 403
    assert retry(world.customer_headers, d.id).status_code in (401, 403)
    assert len(await all_rows(db_session, r.offer_id)) == 1


async def test_retry_rules(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "fail")
    assert retry(r.finance_headers, d.id, "short").status_code == 409
    assert retry(r.finance_headers, uuid4()).status_code == 404
    assert retry(r.finance_headers, d.id).status_code == 201
    # A second retry of the same failed attempt: another one is already live.
    assert retry(r.finance_headers, d.id).status_code == 409
    assert len(await all_rows(db_session, r.offer_id)) == 2


async def test_only_failed_or_reversed_can_be_retried(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "instant")
    assert retry(r.finance_headers, d.id).status_code == 409  # SUCCESS
    body, headers = hook(d.provider_ref, "REVERSED")
    post_hook(body, headers)
    assert retry(r.finance_headers, d.id).status_code == 201  # REVERSED is allowed


async def test_retry_is_blocked_if_the_provider_says_it_was_paid(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "fail")
    # Provider actually paid after we recorded a failure.
    Dev.transactions[d.idempotency_key].update(status="SUCCESS", utr="SURPRISE")
    response = retry(r.finance_headers, d.id)
    assert response.status_code == 409
    rows = await all_rows(db_session, r.offer_id)
    assert len(rows) == 1 and rows[0].status == "REQUIRES_REVIEW"
    assert rows[0].review_reason == "RETRY_BLOCKED_PROVIDER_STATE"


async def test_retry_needs_the_provider_to_confirm_the_failure(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "fail")
    Dev.behaviour = "down"
    assert retry(r.finance_headers, d.id).status_code == 503
    assert len(await all_rows(db_session, r.offer_id)) == 1


# --------------------------------------------------------------- beneficiary


async def test_changed_bank_account_stops_the_payout_before_it_is_sent(
    world, db_session, monkeypatch
):
    r = await ready(world, db_session, monkeypatch)
    create(r.finance_headers, r.offer_id)
    # Customer verifies a different account before the worker runs.
    assert verify_bank(world.customer_headers, acct("5555", "60200123")).json()["status"] == "VERIFIED"
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "REQUIRES_REVIEW" and d.review_reason == "BENEFICIARY_UNAVAILABLE"
    assert Dev.submit_calls == [] and Dev.transactions == {}


# ---------------------------------------------------------------- admin reads


async def test_admin_reads_are_role_restricted_and_masked(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "instant")
    _, auditor = await make_actor(monkeypatch, db_session, role="AUDITOR")
    _, support = await make_actor(monkeypatch, db_session, role="CUSTOMER_SUPPORT")

    ok = client.get(f"/api/v1/admin/disbursements/{d.id}", headers=auditor)
    assert ok.status_code == 200
    data = ok.json()
    assert data["account_number_masked"] == "XXXXXXXX6789" and data["provider_ref"]
    assert NUMBER not in ok.text
    assert client.get(f"/api/v1/admin/disbursements/{d.id}", headers=support).status_code == 403
    assert client.get("/api/v1/admin/disbursements", headers=support).status_code == 403

    listing = client.get("/api/v1/admin/disbursements?status=SUCCESS", headers=auditor)
    assert [x["id"] for x in listing.json()] == [str(d.id)]
    assert client.get("/api/v1/admin/disbursements?status=FAILED", headers=auditor).json() == []
    # Auditors read; they cannot create, retry or recheck.
    assert create(auditor, r.offer_id).status_code == 403
    assert client.get(f"/api/v1/admin/disbursements/{uuid4()}", headers=auditor).status_code == 404


async def test_customer_sees_only_their_own_disbursement(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "instant")
    _, other_headers = await make_actor(monkeypatch, db_session)
    url = f"/api/v1/loan-offers/{r.offer_id}/disbursement"
    assert client.get(url, headers=other_headers).status_code == 404
    assert client.get(url).status_code in (401, 403)
    assert client.get(f"/api/v1/loan-offers/{uuid4()}/disbursement", headers=world.customer_headers).status_code == 404


async def test_admin_detail_includes_webhook_events(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "ok")
    body, headers = hook(d.provider_ref, "SUCCESS", utr="U", event_id="evt-x")
    post_hook(body, headers)
    detail = client.get(f"/api/v1/admin/disbursements/{d.id}", headers=r.finance_headers).json()
    assert [e["provider_event_id"] for e in detail["events"]] == ["evt-x"]
    assert detail["events"][0]["outcome"] == "SUCCESS"


# --------------------------------------------------------- database guarantees


async def test_database_protects_payout_records(world, db_session, monkeypatch):
    r, d = await dispatched(world, db_session, monkeypatch, "instant")
    did, ref = d.id, d.provider_ref
    for statement in (
        "DELETE FROM disbursements WHERE id = :id",
        "UPDATE disbursements SET amount = 1 WHERE id = :id",
        "UPDATE disbursements SET beneficiary_last4 = '0000' WHERE id = :id",
        "UPDATE disbursements SET idempotency_key = 'x' WHERE id = :id",
        "UPDATE disbursements SET provider_ref = 'other' WHERE id = :id",
        "UPDATE disbursements SET status = 'FAILED', completed_at = NULL WHERE id = :id",
        "UPDATE disbursements SET utr = 'changed' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(statement), {"id": did})
        await db_session.rollback()

    # A reversed payout is fully frozen.
    body, headers = hook(ref, "REVERSED")
    post_hook(body, headers)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE disbursements SET failure_code = 'X' WHERE id = :id"), {"id": did}
        )
    await db_session.rollback()


# ----------------------------------------------------------------- worker


async def test_worker_with_nothing_to_do_is_a_noop(world, db_session):
    assert await run_once() == {"claimed": 0, "submitted": 0, "reconciled": 0, "errors": 0}


async def test_development_provider_refused_in_production(monkeypatch):
    from app.providers.factory import get_disbursement_provider

    monkeypatch.setattr(get_settings(), "environment", "production")
    with pytest.raises(RuntimeError):
        get_disbursement_provider()
