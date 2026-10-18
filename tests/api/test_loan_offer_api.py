"""End-to-end 2.8 tests: draft -> issue (KFS+agreement) -> accept, on real Postgres."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.admin_user import AdminUser
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.loan_offer import LoanOffer
from app.models.user import User
from app.services.loan_offer_factory import build_loan_offer_service
from tests.api.test_admin_loan_application import (
    auth_headers,
    authenticate_test_user,
    create_application,
    submit_application,
)

client = TestClient(app)


def phone() -> str:
    return f"9{uuid4().int % 1_000_000_000:09d}"


async def make_actor(monkeypatch, db_session, *, role: str | None = None):
    """Log in a user; if `role` is given, make them an admin with that role."""
    number = phone()
    token = authenticate_test_user(monkeypatch, number)
    row = (
        await db_session.execute(select(User).where(User.phone_number == number))
    ).scalar_one()
    if role is not None:
        db_session.add(AdminUser(user_id=row.id, role=role, is_active=True))
        await db_session.commit()
    return row, auth_headers(token)


async def approved_application(customer_headers, admin_headers, amount="5000.00"):
    application = create_application(customer_headers["Authorization"][7:], amount=amount)
    submit_application(customer_headers["Authorization"][7:], application["id"])
    for body, path in (
        (None, "process"),
        ({"status": "APPROVED", "reason": "test approval"}, "transition"),
    ):
        response = client.post(
            f"/api/v1/admin/loan-applications/{application['id']}/{path}",
            json=body,
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
    return application


def draft_body(application_id, principal="5000.00"):
    return {
        "loan_application_id": application_id,
        "principal_amount": principal,
        "tenure_days": 30,
        "commercial_terms": {"interest_rate": "12", "processing_fee": "100"},
    }


def create_draft(application_id, admin_headers, principal="5000.00"):
    response = client.post(
        "/api/v1/admin/loan-offers",
        json=draft_body(application_id, principal),
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def issue(offer_id, admin_headers, **body):
    return client.post(
        f"/api/v1/admin/loan-offers/{offer_id}/issue",
        json=body or None,
        headers=admin_headers,
    )


@pytest.fixture
async def world(monkeypatch, db_session):
    customer, customer_headers = await make_actor(monkeypatch, db_session)
    admin, admin_headers = await make_actor(
        monkeypatch, db_session, role="SENIOR_UNDERWRITER"
    )
    application = await approved_application(customer_headers, admin_headers)
    return SimpleNamespaceLike(
        customer=customer,
        customer_headers=customer_headers,
        admin=admin,
        admin_headers=admin_headers,
        application=application,
    )


class SimpleNamespaceLike:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def issued_offer(w):
    draft = create_draft(w.application["id"], w.admin_headers)
    response = issue(draft["id"], w.admin_headers)
    assert response.status_code == 200, response.text
    return response.json()


def accept_body(offer):
    return {
        "offer_version": offer["version"],
        "kfs_document_id": offer["kfs_document_id"],
        "kfs_acknowledged": True,
    }


async def audit_actions(db_session, entity_id):
    rows = await db_session.execute(
        select(AuditLog.action).where(AuditLog.entity_id == str(entity_id)).order_by(AuditLog.created_at)
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------- happy path


async def test_full_offer_flow(world, db_session):
    draft = create_draft(world.application["id"], world.admin_headers)
    assert draft["status"] == "DRAFT" and draft["version"] == 1
    assert draft["kfs_document_id"] is None

    # Customer must not see the draft.
    assert client.get("/api/v1/loan-offers", headers=world.customer_headers).json() == []
    assert (
        client.get(f"/api/v1/loan-offers/{draft['id']}", headers=world.customer_headers).status_code
        == 404
    )

    response = issue(draft["id"], world.admin_headers)
    assert response.status_code == 200, response.text
    offer = response.json()
    assert offer["status"] == "ISSUED"
    assert offer["kfs_document_id"] and offer["agreement_document_id"]
    assert offer["kfs_document_id"] != offer["agreement_document_id"]

    listed = client.get("/api/v1/loan-offers", headers=world.customer_headers).json()
    assert [o["id"] for o in listed] == [offer["id"]]

    kfs = client.get(f"/api/v1/loan-offers/{offer['id']}/kfs", headers=world.customer_headers)
    assert kfs.status_code == 200
    assert kfs.headers["content-type"] == "application/pdf"
    assert kfs.headers["cache-control"] == "no-store"
    assert kfs.content.startswith(b"%PDF-")
    assert kfs.headers["x-document-checksum"] == hashlib.sha256(kfs.content).hexdigest()

    agreement = client.get(
        f"/api/v1/loan-offers/{offer['id']}/agreement", headers=world.customer_headers
    )
    assert agreement.status_code == 200 and agreement.content != kfs.content

    accepted = client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept",
        json=accept_body(offer),
        headers=world.customer_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ACCEPTED"
    assert accepted.json()["accepted_at"] is not None

    assert await audit_actions(db_session, offer["id"]) == [
        "LOAN_OFFER_DRAFT_CREATED",
        "LOAN_OFFER_ISSUED",
        "LOAN_OFFER_DOCUMENT_VIEWED",
        "LOAN_OFFER_DOCUMENT_VIEWED",
        "LOAN_OFFER_ACCEPTED",
    ]


async def test_issued_documents_are_immutable_and_linked(world, db_session):
    offer = await issued_offer(world)
    docs = (
        await db_session.execute(
            select(Document).where(Document.loan_offer_id == offer["id"])
        )
    ).scalars().all()

    assert {d.document_type for d in docs} == {"KFS", "LOAN_AGREEMENT"}
    for d in docs:
        assert d.is_immutable
        assert d.owner_id == world.customer.id
        assert d.loan_offer_version == offer["version"]
        assert d.template_key and d.template_version
        assert d.content_type == "application/pdf"


async def test_acceptance_is_idempotent(world, db_session):
    offer = await issued_offer(world)
    url = f"/api/v1/loan-offers/{offer['id']}/accept"
    first = client.post(url, json=accept_body(offer), headers=world.customer_headers)
    second = client.post(url, json=accept_body(offer), headers=world.customer_headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["accepted_at"] == second.json()["accepted_at"]
    actions = await audit_actions(db_session, offer["id"])
    assert actions.count("LOAN_OFFER_ACCEPTED") == 1


async def test_concurrent_acceptance_accepts_once(world, db_session):
    offer = await issued_offer(world)

    async def attempt():
        async with AsyncSessionLocal() as session:
            service = build_loan_offer_service(session)
            result = await service.accept_offer(
                actor_user_id=world.customer.id,
                offer_id=UUID(offer["id"]),
            )
            await session.commit()
            return result.status

    results = await asyncio.gather(attempt(), attempt(), attempt())
    assert results == ["ACCEPTED"] * 3
    actions = await audit_actions(db_session, offer["id"])
    assert actions.count("LOAN_OFFER_ACCEPTED") == 1


# ------------------------------------------------------------ issue behaviour


async def test_reissue_of_same_offer_is_conflict_and_creates_no_extra_documents(world, db_session):
    offer = await issued_offer(world)
    before = (await db_session.execute(select(func.count(Document.id)))).scalar_one()

    again = issue(offer["id"], world.admin_headers)

    assert again.status_code == 409
    after = (await db_session.execute(select(func.count(Document.id)))).scalar_one()
    assert after == before


async def test_new_version_supersedes_previous_issued_offer(world, db_session):
    v1 = await issued_offer(world)
    v2_draft = create_draft(world.application["id"], world.admin_headers, "4000.00")
    assert v2_draft["version"] == 2
    v2 = issue(v2_draft["id"], world.admin_headers).json()

    old = client.get(f"/api/v1/loan-offers/{v1['id']}", headers=world.customer_headers).json()
    assert old["status"] == "CANCELLED"
    # The superseded offer can no longer be accepted.
    stale = client.post(
        f"/api/v1/loan-offers/{v1['id']}/accept",
        json=accept_body(v1),
        headers=world.customer_headers,
    )
    assert stale.status_code == 409
    ok = client.post(
        f"/api/v1/loan-offers/{v2['id']}/accept",
        json=accept_body(v2),
        headers=world.customer_headers,
    )
    assert ok.status_code == 200


async def test_no_new_offer_after_acceptance(world):
    offer = await issued_offer(world)
    client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept",
        json=accept_body(offer),
        headers=world.customer_headers,
    )
    response = client.post(
        "/api/v1/admin/loan-offers",
        json=draft_body(world.application["id"]),
        headers=world.admin_headers,
    )
    assert response.status_code == 409


async def test_db_forbids_two_open_offers_per_application(world, db_session):
    offer = await issued_offer(world)
    draft = create_draft(world.application["id"], world.admin_headers, "1000.00")
    row = (
        await db_session.execute(select(LoanOffer).where(LoanOffer.id == draft["id"]))
    ).scalar_one()
    now = datetime.now(UTC)
    row.status, row.issued_at, row.expires_at = "ISSUED", now, now + timedelta(days=1)
    row.kfs_document_id = UUID(offer["kfs_document_id"])
    row.agreement_document_id = UUID(offer["agreement_document_id"])
    with pytest.raises(IntegrityError, match="uq_loan_offers_one_open_per_application"):
        await db_session.flush()
    await db_session.rollback()


# ------------------------------------------------------------ amount limits


async def test_offer_cannot_exceed_requested_amount(world):
    response = client.post(
        "/api/v1/admin/loan-offers",
        json=draft_body(world.application["id"], "5000.01"),
        headers=world.admin_headers,
    )
    assert response.status_code == 400
    assert "requested amount" in response.json()["detail"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"principal_amount": "0"},
        {"principal_amount": "-1"},
        {"principal_amount": "10.123"},
        {"tenure_days": 0},
        {"commercial_terms": {"rate": 12.5}},  # floats are rejected for money terms
        {"commercial_terms": {"": "x"}},
        {"unexpected": 1},
    ],
)
async def test_draft_payload_validation(world, mutation):
    body = {**draft_body(world.application["id"]), **mutation}
    response = client.post("/api/v1/admin/loan-offers", json=body, headers=world.admin_headers)
    assert response.status_code == 422, response.text


# ------------------------------------------------------------ authorization


async def test_unauthenticated_requests_are_rejected(world):
    assert client.get("/api/v1/loan-offers").status_code in (401, 403)
    assert client.post("/api/v1/admin/loan-offers", json={}).status_code in (401, 403)


async def test_customer_cannot_use_admin_endpoints(world):
    offer = await issued_offer(world)
    for method, path, body in (
        ("post", "/api/v1/admin/loan-offers", draft_body(world.application["id"])),
        ("post", f"/api/v1/admin/loan-offers/{offer['id']}/issue", None),
        ("post", f"/api/v1/admin/loan-offers/{offer['id']}/cancel", {"reason": "x"}),
        ("get", f"/api/v1/admin/loan-offers/{offer['id']}", None),
    ):
        response = getattr(client, method)(path, headers=world.customer_headers, **({"json": body} if body is not None else {}))
        assert response.status_code == 403, (path, response.text)


async def test_underwriter_can_draft_but_cannot_issue_or_cancel(monkeypatch, db_session, world):
    _, headers = await make_actor(monkeypatch, db_session, role="UNDERWRITER")
    draft = client.post(
        "/api/v1/admin/loan-offers", json=draft_body(world.application["id"]), headers=headers
    )
    assert draft.status_code == 201, draft.text

    denied = issue(draft.json()["id"], headers)
    assert denied.status_code == 403
    still = client.get(f"/api/v1/admin/loan-offers/{draft.json()['id']}", headers=world.admin_headers).json()
    assert still["status"] == "DRAFT"

    issued = await issued_offer(world)  # needs its own app state; reuse world's draft path
    cancel = client.post(
        f"/api/v1/admin/loan-offers/{issued['id']}/cancel",
        json={"reason": "no"},
        headers=headers,
    )
    assert cancel.status_code == 403


@pytest.mark.parametrize("role", ["CUSTOMER_SUPPORT", "READ_ONLY", "FINANCE", "AUDITOR"])
async def test_non_underwriting_roles_cannot_create_or_issue(monkeypatch, db_session, world, role):
    _, headers = await make_actor(monkeypatch, db_session, role=role)
    created = client.post(
        "/api/v1/admin/loan-offers", json=draft_body(world.application["id"]), headers=headers
    )
    assert created.status_code == 403
    draft = create_draft(world.application["id"], world.admin_headers)
    assert issue(draft["id"], headers).status_code == 403


async def test_read_only_admin_can_view_offers(monkeypatch, db_session, world):
    _, headers = await make_actor(monkeypatch, db_session, role="READ_ONLY")
    offer = await issued_offer(world)
    got = client.get(f"/api/v1/admin/loan-offers/{offer['id']}", headers=headers)
    assert got.status_code == 200
    listed = client.get(
        "/api/v1/admin/loan-offers",
        params={"loan_application_id": world.application["id"]},
        headers=headers,
    )
    assert [o["id"] for o in listed.json()] == [offer["id"]]


async def test_other_customer_cannot_see_download_accept_or_decline(monkeypatch, db_session, world):
    offer = await issued_offer(world)
    _, stranger = await make_actor(monkeypatch, db_session)

    for method, path, body in (
        ("get", f"/api/v1/loan-offers/{offer['id']}", None),
        ("get", f"/api/v1/loan-offers/{offer['id']}/kfs", None),
        ("get", f"/api/v1/loan-offers/{offer['id']}/agreement", None),
        ("post", f"/api/v1/loan-offers/{offer['id']}/accept", accept_body(offer)),
        ("post", f"/api/v1/loan-offers/{offer['id']}/decline", None),
    ):
        response = getattr(client, method)(path, headers=stranger, **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (path, response.status_code)
    assert client.get("/api/v1/loan-offers", headers=stranger).json() == []


async def test_draft_documents_are_not_downloadable(world):
    draft = create_draft(world.application["id"], world.admin_headers)
    for kind in ("kfs", "agreement"):
        r = client.get(f"/api/v1/loan-offers/{draft['id']}/{kind}", headers=world.customer_headers)
        assert r.status_code == 404


# ------------------------------------------------------------ acceptance rules


async def test_accept_requires_acknowledgement_and_matching_version(world):
    offer = await issued_offer(world)
    url = f"/api/v1/loan-offers/{offer['id']}/accept"

    not_ack = client.post(url, json={**accept_body(offer), "kfs_acknowledged": False}, headers=world.customer_headers)
    assert not_ack.status_code == 422

    stale = client.post(url, json={**accept_body(offer), "offer_version": 99}, headers=world.customer_headers)
    assert stale.status_code == 409

    wrong_kfs = client.post(url, json={**accept_body(offer), "kfs_document_id": str(uuid4())}, headers=world.customer_headers)
    assert wrong_kfs.status_code == 409

    current = client.get(f"/api/v1/loan-offers/{offer['id']}", headers=world.customer_headers).json()
    assert current["status"] == "ISSUED"


def fast_forward(monkeypatch, days=30):
    """Move the offer clock forward (issued offers are immutable in the DB)."""
    import app.domain.loan_offer as offer_domain

    real = offer_domain.utcnow
    monkeypatch.setattr(
        offer_domain, "utcnow", lambda: real() + timedelta(days=days)
    )


async def test_expired_offer_cannot_be_accepted_and_state_sticks(world, db_session, monkeypatch):
    offer = await issued_offer(world)
    fast_forward(monkeypatch)

    # Reads already show EXPIRED although the stored row still says ISSUED.
    seen = client.get(f"/api/v1/loan-offers/{offer['id']}", headers=world.customer_headers).json()
    assert seen["status"] == "EXPIRED"

    response = client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept",
        json=accept_body(offer),
        headers=world.customer_headers,
    )
    assert response.status_code == 409

    db_session.expire_all()
    row = (await db_session.execute(select(LoanOffer).where(LoanOffer.id == offer["id"]))).scalar_one()
    assert row.status == "EXPIRED" and row.accepted_at is None


async def test_admin_sees_stored_and_effective_status(world, monkeypatch):
    offer = await issued_offer(world)
    fast_forward(monkeypatch)
    got = client.get(f"/api/v1/admin/loan-offers/{offer['id']}", headers=world.admin_headers).json()
    assert got["status"] == "ISSUED" and got["effective_status"] == "EXPIRED"


async def test_expiry_sweep_expires_due_offers_once(world, db_session, monkeypatch):
    offer = await issued_offer(world)
    fast_forward(monkeypatch)

    async with AsyncSessionLocal() as session:
        swept = await build_loan_offer_service(session).expire_due_offers()
        await session.commit()
    async with AsyncSessionLocal() as session:
        again = await build_loan_offer_service(session).expire_due_offers()
        await session.commit()

    assert (swept, again) == (1, 0)
    row = client.get(f"/api/v1/admin/loan-offers/{offer['id']}", headers=world.admin_headers).json()
    assert row["status"] == "EXPIRED"
    assert "LOAN_OFFER_EXPIRED" in await audit_actions(db_session, offer["id"])


async def test_decline_then_cannot_accept(world):
    offer = await issued_offer(world)
    declined = client.post(f"/api/v1/loan-offers/{offer['id']}/decline", headers=world.customer_headers)
    assert declined.status_code == 200 and declined.json()["status"] == "DECLINED"
    again = client.post(f"/api/v1/loan-offers/{offer['id']}/decline", headers=world.customer_headers)
    assert again.status_code == 200
    accept = client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept", json=accept_body(offer), headers=world.customer_headers
    )
    assert accept.status_code == 409


async def test_cancel_requires_reason_and_blocks_acceptance(world, db_session):
    offer = await issued_offer(world)
    url = f"/api/v1/admin/loan-offers/{offer['id']}/cancel"

    assert client.post(url, json={"reason": "   "}, headers=world.admin_headers).status_code == 422

    cancelled = client.post(url, json={"reason": "Terms entered incorrectly"}, headers=world.admin_headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"

    accept = client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept", json=accept_body(offer), headers=world.customer_headers
    )
    assert accept.status_code == 409
    log = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.entity_id == offer["id"], AuditLog.action == "LOAN_OFFER_CANCELLED")
        )
    ).scalar_one()
    assert log.reason == "Terms entered incorrectly"
    assert log.actor_role == "SENIOR_UNDERWRITER"


# ------------------------------------------------------------ audit


async def test_customer_audit_rows_identify_the_customer(world, db_session):
    offer = await issued_offer(world)
    client.post(
        f"/api/v1/loan-offers/{offer['id']}/accept", json=accept_body(offer), headers=world.customer_headers
    )
    row = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.entity_id == offer["id"], AuditLog.action == "LOAN_OFFER_ACCEPTED")
        )
    ).scalar_one()
    assert row.actor_role == "CUSTOMER"
    assert row.actor_admin_user_id is None
    assert row.event_metadata["actor_user_id"] == str(world.customer.id)
    assert row.new_value["kfs_document_id"] == offer["kfs_document_id"]
    assert row.request_id  # RequestIDMiddleware id propagated


async def test_production_refuses_draft_templates(world, monkeypatch):
    from app.core.config import get_settings

    from app.providers.storage_development import DevelopmentDocumentStorage

    draft = create_draft(world.application["id"], world.admin_headers)
    # Isolate the template gate from the (separate) production-storage guard.
    monkeypatch.setattr(
        "app.services.document.get_document_storage",
        lambda: DevelopmentDocumentStorage(),
    )
    monkeypatch.setattr(get_settings(), "environment", "production")
    response = issue(draft["id"], world.admin_headers)
    assert response.status_code == 409
    assert "not approved" in response.json()["detail"]
    monkeypatch.undo()


async def test_offer_documents_live_in_encrypted_s3_not_the_database(world, monkeypatch):
    """Issue and download through the S3 provider (moto), end to end."""
    import boto3
    from moto import mock_aws

    from app.providers.storage_s3 import S3DocumentStorage

    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-south-1")
        s3.create_bucket(
            Bucket="offer-docs",
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        monkeypatch.setattr(
            "app.services.document.get_document_storage",
            lambda: S3DocumentStorage(bucket="offer-docs", client=s3, prefix="docs"),
        )

        offer = await issued_offer(world)

        objects = s3.list_objects_v2(Bucket="offer-docs")["Contents"]
        assert len(objects) == 2
        for obj in objects:
            assert obj["Key"].startswith("docs/")
            head = s3.head_object(Bucket="offer-docs", Key=obj["Key"])
            assert head["ServerSideEncryption"] == "AES256"
            assert head["ContentType"] == "application/pdf"

        kfs = client.get(f"/api/v1/loan-offers/{offer['id']}/kfs", headers=world.customer_headers)
        assert kfs.status_code == 200 and kfs.content.startswith(b"%PDF-")
        assert kfs.headers["x-document-checksum"] == hashlib.sha256(kfs.content).hexdigest()
