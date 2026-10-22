"""End-to-end 2.9 e-sign tests on real Postgres with the development provider."""

import base64
import json
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import get_settings
from app.domain import loan_offer as offer_domain
from app.main import app
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.esign_event import ESignEvent
from app.models.esign_transaction import ESignTransaction
from app.providers.esign_development import DevelopmentESignProvider, sign_callback
from app.services.document import DocumentService
from tests.api.test_loan_offer_api import (  # noqa: F401  (world is a fixture)
    SimpleNamespaceLike,
    accept_body,
    issued_offer,
    make_actor,
    world,
)

client = TestClient(app)
SECRET = "unit-test-webhook-secret"
SIGNED_PDF = b"%PDF-1.4\n% signed copy\n"


@pytest.fixture(autouse=True)
def esign_env(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "esign_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "esign_require_signed_artifact", True)
    DevelopmentESignProvider.reset()
    yield
    DevelopmentESignProvider.reset()


# ------------------------------------------------------------------ helpers


async def accepted_offer(w):
    offer = await issued_offer(w)
    response = client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept",
        json=accept_body(offer),
        headers=w.customer_headers,
    )
    assert response.status_code == 200, response.text
    return offer


def start(offer_id, headers):
    return client.post(f"/api/v1/loan-offers/{offer_id}/esign", headers=headers)


def status_of(offer_id, headers):
    return client.get(f"/api/v1/loan-offers/{offer_id}/esign", headers=headers)


async def load_tx(db_session, offer_id):
    db_session.expire_all()
    return (
        await db_session.execute(
            select(ESignTransaction)
            .where(ESignTransaction.loan_offer_id == offer_id)
            .order_by(ESignTransaction.created_at.desc())
        )
    ).scalars().first()


def callback(
    ref,
    status,
    checksum,
    *,
    event_id=None,
    signed=SIGNED_PDF,
    secret=SECRET,
    timestamp=None,
    **extra,
):
    payload = {
        "event_id": event_id or f"evt-{uuid4()}",
        "provider_ref": ref,
        "status": status,
        "document_checksum": checksum,
        "occurred_at": offer_domain.utcnow().isoformat(),
        **extra,
    }
    if signed is not None:
        payload["signed_document_b64"] = base64.b64encode(signed).decode()
    body = json.dumps(payload).encode()
    headers = sign_callback(secret, body, timestamp) if secret else {}
    headers["Content-Type"] = "application/json"
    return body, headers


def post_callback(body, headers, provider="development"):
    return client.post(f"/api/v1/webhooks/esign/{provider}", content=body, headers=headers)


async def pending_tx(w, db_session):
    offer = await accepted_offer(w)
    response = start(offer["id"], w.customer_headers)
    assert response.status_code == 200, response.text
    tx = await load_tx(db_session, offer["id"])
    return offer, tx


async def audit_actions(db_session, entity_id):
    rows = await db_session.execute(
        select(AuditLog.action).where(AuditLog.entity_id == str(entity_id))
    )
    return [r[0] for r in rows]


# ------------------------------------------------------------------ success


async def test_initiate_records_transaction_bound_to_exact_document(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    assert tx.status == "PENDING"
    assert tx.provider == "development" and tx.provider_ref.startswith("dev-esign-")
    assert str(tx.document_id) == offer["agreement_document_id"]
    assert tx.loan_offer_version == offer["version"]
    doc = await db_session.get(Document, tx.document_id)
    assert tx.document_checksum == doc.checksum
    assert tx.expires_at > offer_domain.utcnow()

    body = status_of(offer["id"], world.customer_headers).json()
    assert body["status"] == "PENDING"
    assert body["signing_url"].startswith("https://esign.invalid/")
    assert "provider_ref" not in body and "document_checksum" not in body


async def test_initiate_is_idempotent(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    again = start(offer["id"], world.customer_headers)
    assert again.status_code == 200 and again.json()["id"] == str(tx.id)
    count = (
        await db_session.execute(select(func.count()).select_from(ESignTransaction))
    ).scalar_one()
    assert count == 1


async def test_successful_signing_stores_artifact_and_metadata(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    response = post_callback(body, headers)
    assert response.status_code == 200 and response.json()["outcome"] == "SIGNED"

    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "SIGNED" and tx.signed_at is not None
    signed = await db_session.get(Document, tx.signed_document_id)
    assert signed.document_type == "SIGNED_AGREEMENT" and signed.is_immutable
    assert signed.loan_offer_id == tx.loan_offer_id
    assert signed.loan_offer_version == tx.loan_offer_version
    assert signed.checksum == tx.signed_checksum
    assert signed.checksum != tx.document_checksum
    stored = await DocumentService(db_session).storage.get(signed.storage_ref)
    assert stored.content == SIGNED_PDF

    assert status_of(offer["id"], world.customer_headers).json()["status"] == "SIGNED"
    download = client.get(
        f"/api/v1/loan-offers/{offer['id']}/signed-agreement",
        headers=world.customer_headers,
    )
    assert download.status_code == 200 and download.content == SIGNED_PDF
    assert download.headers["cache-control"] == "no-store"

    actions = await audit_actions(db_session, tx.id)
    assert {"ESIGN_INITIATED", "ESIGN_PENDING", "ESIGN_SIGNED"} <= set(actions)
    assert "ESIGN_SIGNED_DOCUMENT_VIEWED" in actions


async def test_artifact_fetched_from_provider_when_not_in_callback(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    DevelopmentESignProvider.transactions[tx.provider_ref]["signed"] = SIGNED_PDF
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum, signed=None)
    assert post_callback(body, headers).json()["outcome"] == "SIGNED"
    tx = await load_tx(db_session, offer["id"])
    assert tx.signed_document_id is not None


async def test_missing_artifact_goes_to_manual_review_when_required(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum, signed=None)
    assert post_callback(body, headers).json()["outcome"] == "SIGNED_ARTIFACT_UNAVAILABLE"
    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "MANUAL_REVIEW" and tx.signed_document_id is None
    assert status_of(offer["id"], world.customer_headers).json()["status"] == "UNDER_REVIEW"


async def test_missing_artifact_allowed_when_not_required(world, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "esign_require_signed_artifact", False)
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum, signed=None)
    assert post_callback(body, headers).json()["outcome"] == "SIGNED"
    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "SIGNED" and tx.signed_document_id is None


async def test_invalid_artifact_goes_to_manual_review(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(
        tx.provider_ref, "SIGNED", tx.document_checksum, signed=b"not a pdf"
    )
    assert post_callback(body, headers).json()["outcome"] == "SIGNED_ARTIFACT_INVALID"
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


# ------------------------------------------------------------------ failure


async def test_failed_callback_then_retry_uses_new_reference(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(
        tx.provider_ref, "FAILED", tx.document_checksum, signed=None,
        failure_reason="signer declined",
    )
    assert post_callback(body, headers).status_code == 200
    failed = await load_tx(db_session, offer["id"])
    assert failed.status == "FAILED" and failed.failure_reason == "signer declined"
    # Customers never see provider failure detail.
    assert "signer declined" not in status_of(offer["id"], world.customer_headers).text

    retry = start(offer["id"], world.customer_headers)
    assert retry.status_code == 200 and retry.json()["status"] == "PENDING"
    second = await load_tx(db_session, offer["id"])
    assert second.id != failed.id
    assert second.client_reference != failed.client_reference
    assert second.provider_ref != failed.provider_ref


async def test_provider_rejection_marks_failed(world, db_session):
    offer = await accepted_offer(world)
    DevelopmentESignProvider.behaviour = "reject"
    response = start(offer["id"], world.customer_headers)
    assert response.status_code == 200 and response.json()["status"] == "FAILED"
    assert (await load_tx(db_session, offer["id"])).status == "FAILED"


# ------------------------------------------------------------------ timeout


async def test_provider_timeout_keeps_initiated_and_retry_reuses_reference(
    world, db_session
):
    offer = await accepted_offer(world)
    DevelopmentESignProvider.behaviour = "timeout"
    response = start(offer["id"], world.customer_headers)
    assert response.status_code == 503 and "Retry-After" in response.headers

    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "INITIATED" and tx.provider_ref is None
    reference = tx.client_reference
    assert status_of(offer["id"], world.customer_headers).json()["status"] == "PENDING"

    DevelopmentESignProvider.behaviour = "ok"
    retry = start(offer["id"], world.customer_headers)
    assert retry.status_code == 200
    again = await load_tx(db_session, offer["id"])
    assert again.id == tx.id and again.client_reference == reference
    assert again.status == "PENDING" and again.provider_ref is not None


async def test_sync_expires_overdue_transactions(world, db_session, monkeypatch):
    from app.repositories.esign import ESignRepository
    from app.services.esign_factory import build_esign_service

    offer, tx = await pending_tx(world, db_session)
    real = offer_domain.utcnow
    monkeypatch.setattr(
        offer_domain, "utcnow", lambda: real() + timedelta(hours=100)
    )
    service = build_esign_service(db_session)
    counts = await service.sync_pending()
    await db_session.commit()
    assert counts["expired"] == 1
    assert (await load_tx(db_session, offer["id"])).status == "EXPIRED"
    assert ESignRepository  # imported for clarity


async def test_sync_polls_provider_for_missed_callback(world, db_session):
    from app.services.esign_factory import build_esign_service

    offer, tx = await pending_tx(world, db_session)
    provider_tx = DevelopmentESignProvider.transactions[tx.provider_ref]
    provider_tx["status"] = "SIGNED"
    provider_tx["signed"] = SIGNED_PDF
    counts = await build_esign_service(db_session).sync_pending()
    await db_session.commit()
    assert counts["updated"] == 1
    assert (await load_tx(db_session, offer["id"])).status == "SIGNED"


async def test_sync_resumes_initiated_after_timeout(world, db_session):
    from app.services.esign_factory import build_esign_service

    offer = await accepted_offer(world)
    DevelopmentESignProvider.behaviour = "timeout"
    assert start(offer["id"], world.customer_headers).status_code == 503
    DevelopmentESignProvider.behaviour = "ok"
    await build_esign_service(db_session).sync_pending()
    await db_session.commit()
    assert (await load_tx(db_session, offer["id"])).status == "PENDING"


# ---------------------------------------------------------------- duplicates


async def test_duplicate_callback_is_safe(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(
        tx.provider_ref, "SIGNED", tx.document_checksum, event_id="evt-fixed"
    )
    first = post_callback(body, headers)
    second = post_callback(body, sign_callback_headers(body))
    assert first.json()["outcome"] == "SIGNED"
    assert second.status_code == 200 and second.json()["outcome"] == "DUPLICATE"

    events = (
        await db_session.execute(select(func.count()).select_from(ESignEvent))
    ).scalar_one()
    signed_docs = (
        await db_session.execute(
            select(func.count()).select_from(Document).where(
                Document.document_type == "SIGNED_AGREEMENT"
            )
        )
    ).scalar_one()
    assert events == 1 and signed_docs == 1
    actions = await audit_actions(db_session, tx.id)
    assert actions.count("ESIGN_SIGNED") == 1


def sign_callback_headers(body):
    headers = sign_callback(SECRET, body)
    headers["Content-Type"] = "application/json"
    return headers


async def test_same_signed_report_with_new_event_id_changes_nothing(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    post_callback(body, headers)
    body2, headers2 = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    assert post_callback(body2, headers2).json()["outcome"] == "DUPLICATE_SIGNED"
    assert (await audit_actions(db_session, tx.id)).count("ESIGN_SIGNED") == 1


async def test_conflicting_callback_after_signed_is_ignored(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    post_callback(body, headers)
    body2, headers2 = callback(tx.provider_ref, "FAILED", tx.document_checksum, signed=None)
    assert post_callback(body2, headers2).json()["outcome"] == "IGNORED_AFTER_SIGNED"
    assert (await load_tx(db_session, offer["id"])).status == "SIGNED"


# ------------------------------------------------- wrong document / version


async def test_callback_for_wrong_document_goes_to_manual_review(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", "0" * 64)
    assert post_callback(body, headers).json()["outcome"] == "DOCUMENT_MISMATCH"
    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "MANUAL_REVIEW" and tx.signed_document_id is None
    assert (
        await db_session.execute(
            select(func.count()).select_from(Document).where(
                Document.document_type == "SIGNED_AGREEMENT"
            )
        )
    ).scalar_one() == 0


async def test_signed_callback_without_document_reference_is_not_trusted(
    world, db_session
):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", None)
    assert (
        post_callback(body, headers).json()["outcome"]
        == "SIGNED_WITHOUT_DOCUMENT_REFERENCE"
    )
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


async def test_wrong_checksum_failure_callback_cannot_fail_the_transaction(
    world, db_session
):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "FAILED", "f" * 64, signed=None)
    post_callback(body, headers)
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


async def test_late_signed_after_failed_goes_to_manual_review(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "FAILED", tx.document_checksum, signed=None)
    post_callback(body, headers)
    body2, headers2 = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    assert post_callback(body2, headers2).json()["outcome"] == "LATE_SIGNED"
    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "MANUAL_REVIEW" and tx.signed_document_id is None


async def test_signed_after_expiry_goes_to_manual_review(world, db_session, monkeypatch):
    offer, tx = await pending_tx(world, db_session)
    real = offer_domain.utcnow
    monkeypatch.setattr(offer_domain, "utcnow", lambda: real() + timedelta(hours=100))
    body, headers = callback(
        tx.provider_ref, "SIGNED", tx.document_checksum,
        occurred_at=(real() + timedelta(hours=99)).isoformat(),
    )
    assert post_callback(body, headers).json()["outcome"] == "SIGNED_AFTER_EXPIRY"


async def test_unknown_reference_is_404_and_stores_nothing(world, db_session):
    await accepted_offer(world)
    body, headers = callback("dev-esign-unknown", "SIGNED", "a" * 64)
    assert post_callback(body, headers).status_code == 404
    assert (
        await db_session.execute(select(func.count()).select_from(ESignEvent))
    ).scalar_one() == 0


async def test_tampered_agreement_blocks_initiation(world, db_session, monkeypatch):
    from app.providers.storage import StoredDocumentContent
    from app.providers.storage_development import DevelopmentDocumentStorage

    offer = await accepted_offer(world)

    async def tampered(self, storage_ref):
        return StoredDocumentContent(content=b"%PDF-1.4 tampered", content_type="application/pdf")

    monkeypatch.setattr(DevelopmentDocumentStorage, "get", tampered)
    response = start(offer["id"], world.customer_headers)
    assert response.status_code == 409
    assert (await load_tx(db_session, offer["id"])) is None


# ---------------------------------------------------------------- signatures


async def test_bad_signatures_are_rejected_and_store_nothing(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    good_body, good_headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)

    wrong_secret = callback(tx.provider_ref, "SIGNED", tx.document_checksum, secret="other")
    no_headers = (good_body, {"Content-Type": "application/json"})
    stale = callback(
        tx.provider_ref, "SIGNED", tx.document_checksum,
        timestamp=int(time.time()) - 10_000,
    )
    tampered = (good_body.replace(b"SIGNED", b"FAILED"), good_headers)
    bad_ts = (good_body, {**good_headers, "X-ESign-Timestamp": "abc"})
    for body, headers in (wrong_secret, no_headers, stale, tampered, bad_ts):
        assert post_callback(body, headers).status_code == 401

    assert (
        await db_session.execute(select(func.count()).select_from(ESignEvent))
    ).scalar_one() == 0
    assert (await load_tx(db_session, offer["id"])).status == "PENDING"


async def test_callbacks_rejected_when_secret_not_configured(world, db_session, monkeypatch):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    monkeypatch.setattr(get_settings(), "esign_webhook_secret", None)
    assert post_callback(body, headers).status_code == 401


async def test_unknown_provider_in_url_is_404(world, db_session):
    body, headers = callback("x", "SIGNED", "a" * 64)
    assert post_callback(body, headers, provider="acme").status_code == 404


async def test_malformed_but_authentic_body_is_400(world, db_session):
    body = b"not json"
    assert post_callback(body, sign_callback_headers(body)).status_code == 400
    body = json.dumps({"event_id": "e", "provider_ref": "r", "status": "WEIRD"}).encode()
    assert post_callback(body, sign_callback_headers(body)).status_code == 400


# ------------------------------------------------------------- authorization


async def test_other_customer_cannot_touch_someone_elses_signing(
    world, db_session, monkeypatch
):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    post_callback(body, headers)
    _, other_headers = await make_actor(monkeypatch, db_session)
    for response in (
        start(offer["id"], other_headers),
        status_of(offer["id"], other_headers),
        client.get(f"/api/v1/loan-offers/{offer['id']}/signed-agreement", headers=other_headers),
    ):
        assert response.status_code == 404


async def test_unauthenticated_requests_are_rejected(world, db_session):
    offer = await accepted_offer(world)
    for response in (
        client.post(f"/api/v1/loan-offers/{offer['id']}/esign"),
        client.get(f"/api/v1/loan-offers/{offer['id']}/esign"),
        client.get(f"/api/v1/loan-offers/{offer['id']}/signed-agreement"),
        client.get(f"/api/v1/admin/loan-offers/{offer['id']}/esign"),
    ):
        assert response.status_code in (401, 403)


async def test_offer_must_be_accepted_before_signing(world, db_session):
    offer = await issued_offer(world)
    assert start(offer["id"], world.customer_headers).status_code == 409


async def test_signed_agreement_unavailable_until_signed(world, db_session):
    offer, _ = await pending_tx(world, db_session)
    response = client.get(
        f"/api/v1/loan-offers/{offer['id']}/signed-agreement",
        headers=world.customer_headers,
    )
    assert response.status_code == 404


async def test_admin_read_requires_permission(world, db_session, monkeypatch):
    offer, tx = await pending_tx(world, db_session)
    ok = client.get(
        f"/api/v1/admin/loan-offers/{offer['id']}/esign", headers=world.admin_headers
    )
    assert ok.status_code == 200
    data = ok.json()
    assert data["provider_ref"] == tx.provider_ref and data["status"] == "PENDING"

    # A customer (not an admin) must be refused.
    denied = client.get(
        f"/api/v1/admin/loan-offers/{offer['id']}/esign", headers=world.customer_headers
    )
    assert denied.status_code in (401, 403)


# --------------------------------------------------------- database guarantees


async def test_one_live_transaction_per_offer_in_database(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    db_session.add(
        ESignTransaction(
            user_id=tx.user_id,
            loan_offer_id=tx.loan_offer_id,
            loan_offer_version=tx.loan_offer_version,
            document_id=tx.document_id,
            document_checksum=tx.document_checksum,
            provider="development",
            client_reference="dup",
            status="INITIATED",
            expires_at=tx.expires_at,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_signed_transaction_is_immutable_in_database(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum)
    post_callback(body, headers)
    tx_id = tx.id
    for statement in (
        "UPDATE esign_transactions SET failure_reason = 'x' WHERE id = :id",
        "UPDATE esign_transactions SET status = 'FAILED', signed_at = NULL WHERE id = :id",
        "UPDATE esign_transactions SET document_checksum = repeat('a', 64) WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(statement), {"id": tx_id})
        await db_session.rollback()


async def test_binding_fields_cannot_change_while_pending(world, db_session):
    offer, tx = await pending_tx(world, db_session)
    tx_id = tx.id
    for statement in (
        "UPDATE esign_transactions SET document_checksum = repeat('b', 64) WHERE id = :id",
        "UPDATE esign_transactions SET provider_ref = 'other' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(statement), {"id": tx_id})
        await db_session.rollback()


# ------------------------------------------------------ manual review workflow


async def review_tx(world, db_session):
    """A transaction in MANUAL_REVIEW (signed callback without any artifact)."""
    offer, tx = await pending_tx(world, db_session)
    body, headers = callback(tx.provider_ref, "SIGNED", tx.document_checksum, signed=None)
    assert post_callback(body, headers).json()["outcome"] == "SIGNED_ARTIFACT_UNAVAILABLE"
    return offer, await load_tx(db_session, offer["id"])


def resolve_review(headers, offer_id, decision, reason="Checked with the provider dashboard"):
    return client.post(
        f"/api/v1/admin/loan-offers/{offer_id}/esign/resolve",
        json={"decision": decision, "reason": reason},
        headers=headers,
    )


async def test_review_queue_lists_transactions_for_authorised_admins(world, db_session):
    offer, tx = await review_tx(world, db_session)
    queue = client.get("/api/v1/admin/loan-offers/esign/review-queue", headers=world.admin_headers)
    assert queue.status_code == 200
    assert [row["id"] for row in queue.json()] == [str(tx.id)]
    assert queue.json()[0]["status"] == "MANUAL_REVIEW"


async def test_recheck_completes_signing_when_provider_confirms(world, db_session):
    offer, tx = await review_tx(world, db_session)
    provider_tx = DevelopmentESignProvider.transactions[tx.provider_ref]
    provider_tx.update(status="SIGNED", signed=SIGNED_PDF)

    response = resolve_review(world.admin_headers, offer["id"], "RECHECK")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SIGNED"
    tx = await load_tx(db_session, offer["id"])
    assert tx.status == "SIGNED" and tx.signed_document_id is not None
    assert tx.reviewed_by_admin_user_id is not None and tx.resolution_reason
    stored = await DocumentService(db_session).storage.get(
        (await db_session.get(Document, tx.signed_document_id)).storage_ref
    )
    assert stored.content == SIGNED_PDF
    log = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "ESIGN_REVIEW_RESOLVED")
        )
    ).scalar_one()
    assert log.old_value["status"] == "MANUAL_REVIEW" and log.new_value["status"] == "SIGNED"
    assert log.reason


async def test_recheck_never_signs_on_an_admins_word(world, db_session):
    offer, tx = await review_tx(world, db_session)
    # Provider still pending: no state change, whatever the admin wants.
    assert resolve_review(world.admin_headers, offer["id"], "RECHECK").status_code == 409
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"
    # Provider reports a different document.
    provider_tx = DevelopmentESignProvider.transactions[tx.provider_ref]
    provider_tx.update(status="SIGNED", document_checksum="e" * 64, signed=SIGNED_PDF)
    assert resolve_review(world.admin_headers, offer["id"], "RECHECK").status_code == 409
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"
    # Provider confirms but no artifact obtainable while one is required.
    provider_tx.update(document_checksum=tx.document_checksum, signed=None)
    assert resolve_review(world.admin_headers, offer["id"], "RECHECK").status_code == 409
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


async def test_recheck_fails_transaction_when_provider_says_failed(world, db_session):
    offer, tx = await review_tx(world, db_session)
    DevelopmentESignProvider.transactions[tx.provider_ref]["status"] = "FAILED"
    assert resolve_review(world.admin_headers, offer["id"], "RECHECK").json()["status"] == "FAILED"
    # Customer can start a fresh attempt afterwards.
    assert start(offer["id"], world.customer_headers).json()["status"] == "PENDING"


async def test_failing_a_review_is_refused_if_provider_confirms_signature(world, db_session):
    offer, tx = await review_tx(world, db_session)
    DevelopmentESignProvider.transactions[tx.provider_ref].update(
        status="SIGNED", signed=SIGNED_PDF
    )
    assert resolve_review(world.admin_headers, offer["id"], "FAILED").status_code == 409
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


async def test_failing_a_review_allows_a_retry(world, db_session):
    offer, tx = await review_tx(world, db_session)
    response = resolve_review(world.admin_headers, offer["id"], "FAILED")
    assert response.status_code == 200 and response.json()["status"] == "FAILED"
    assert response.json()["resolution_reason"]
    assert start(offer["id"], world.customer_headers).json()["status"] == "PENDING"


async def test_review_resolution_is_permission_controlled(world, db_session, monkeypatch):
    offer, tx = await review_tx(world, db_session)
    for role in ("FINANCE", "KYC_REVIEWER", "AUDITOR", "CUSTOMER_SUPPORT"):
        _, headers = await make_actor(monkeypatch, db_session, role=role)
        assert resolve_review(headers, offer["id"], "FAILED").status_code == 403
        assert client.get(
            "/api/v1/admin/loan-offers/esign/review-queue", headers=headers
        ).status_code == 403
    assert resolve_review(world.customer_headers, offer["id"], "FAILED").status_code in (401, 403)
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


async def test_review_resolution_validation_and_state_rules(world, db_session):
    offer, tx = await review_tx(world, db_session)
    assert resolve_review(world.admin_headers, offer["id"], "SIGNED").status_code == 409
    assert resolve_review(world.admin_headers, offer["id"], "FAILED", "short").status_code == 409
    assert resolve_review(world.admin_headers, offer["id"], "FAILED").status_code == 200
    # Already resolved: nothing awaiting review any more.
    assert resolve_review(world.admin_headers, offer["id"], "FAILED").status_code == 409


async def test_provider_outage_blocks_review_resolution(world, db_session):
    offer, tx = await review_tx(world, db_session)
    DevelopmentESignProvider.behaviour = "timeout"
    assert resolve_review(world.admin_headers, offer["id"], "FAILED").status_code == 503
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"


async def test_admin_cannot_review_their_own_signing(world, db_session):
    from app.models.admin_user import AdminUser

    customer_id = world.customer.id
    offer, tx = await review_tx(world, db_session)
    # The customer is also an admin with review rights (a conflict of interest).
    db_session.add(AdminUser(user_id=customer_id, role="SENIOR_UNDERWRITER", is_active=True))
    await db_session.commit()
    response = resolve_review(world.customer_headers, offer["id"], "FAILED")
    assert response.status_code == 403
    assert (await load_tx(db_session, offer["id"])).status == "MANUAL_REVIEW"
