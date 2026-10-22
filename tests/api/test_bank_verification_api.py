"""End-to-end 2.10 bank verification tests on real Postgres + dev provider."""

import base64
import json
import logging
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import get_settings
from app.core.encryption import EncryptionError
from app.domain import bank_verification as bank_domain
from app.main import app
from app.models.audit_log import AuditLog
from app.models.bank_account_verification import BankAccountVerification as Row
from app.models.user_profile import UserProfile
from app.providers.bank_verification_development import (
    DevelopmentBankVerificationProvider as Dev,
)
from app.services.bank_verification_factory import build_bank_verification_service
from types import SimpleNamespace

from tests.api.test_loan_offer_api import make_actor as _make_actor

client = TestClient(app)

K1 = base64.b64encode(b"1" * 32).decode()
K2 = base64.b64encode(b"2" * 32).decode()
FP = base64.b64encode(b"f" * 32).decode()
IFSC = "HDFC0001234"


def acct(tail: str, head: str = "50100123") -> str:
    return f"{head}{tail}"  # 12 digits


@pytest.fixture(autouse=True)
def bank_env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "field_encryption_keys", f"k1:{K1},k2:{K2}")
    monkeypatch.setattr(s, "field_encryption_active_key_id", "k1")
    monkeypatch.setattr(s, "bank_fingerprint_key", FP)
    monkeypatch.setattr(s, "bank_verification_max_attempts_per_day", 5)
    Dev.reset()
    yield
    Dev.reset()


async def make_actor(monkeypatch, db_session, *, role=None):
    # Capture the id: ORM instances are expired by later session activity.
    row, headers = await _make_actor(monkeypatch, db_session, role=role)
    return SimpleNamespace(id=row.id), headers


async def customer(monkeypatch, db_session, *, profile=True):
    user, headers = await make_actor(monkeypatch, db_session)
    if profile:
        db_session.add(UserProfile(user_id=user.id, first_name="Asha", last_name="Rao"))
        await db_session.commit()
    return user, headers


def verify(headers, number, ifsc=IFSC):
    return client.post(
        "/api/v1/bank-verifications",
        json={"account_number": number, "ifsc": ifsc},
        headers=headers,
    )


async def rows_for(db_session, user_id):
    db_session.expire_all()
    return (
        await db_session.execute(
            select(Row).where(Row.user_id == user_id).order_by(Row.requested_at)
        )
    ).scalars().all()


async def audit_blob(db_session) -> str:
    rows = await db_session.execute(
        select(AuditLog.event_metadata, AuditLog.new_value, AuditLog.old_value, AuditLog.reason)
    )
    return json.dumps([list(r) for r in rows], default=str)


async def audit_actions(db_session, entity_id=None):
    stmt = select(AuditLog.action)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == str(entity_id))
    return [r[0] for r in await db_session.execute(stmt)]


# ------------------------------------------------------------------ success


async def test_verified_account_is_masked_encrypted_and_minimal(
    monkeypatch, db_session, caplog
):
    caplog.set_level(logging.DEBUG)
    user, headers = await customer(monkeypatch, db_session)
    number = acct("6789")
    response = verify(headers, number)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "VERIFIED"
    assert body["account_number_masked"] == "XXXXXXXX6789"
    assert number not in response.text and "6789" not in response.text.replace("XXXXXXXX6789", "")
    assert body["bank_name"] == "Dev Test Bank"
    assert "provider_ref" not in body and "fingerprint" not in response.text

    (row,) = await rows_for(db_session, user.id)
    assert row.status == "VERIFIED" and row.verified_at is not None
    assert row.account_last4 == "6789" and row.ifsc == IFSC
    assert number not in row.account_number_encrypted
    assert row.account_number_encrypted.startswith("v1:k1:")
    assert row.encryption_key_id == "k1"
    assert len(row.account_fingerprint) == 64 and number not in row.account_fingerprint
    assert row.provider_ref.startswith("dev-bank-")
    assert row.name_match_result == "MATCH"
    assert number not in repr(row)

    current = client.get("/api/v1/bank-verifications/current", headers=headers)
    assert current.status_code == 200 and current.json()["id"] == body["id"]

    # Nothing sensitive in logs or audit records.
    assert number not in caplog.text
    assert number not in await audit_blob(db_session)
    assert {"BANK_VERIFICATION_REQUESTED", "BANK_VERIFICATION_VERIFIED"} <= set(
        await audit_actions(db_session, row.id)
    )


async def test_validation_errors_never_echo_the_input(monkeypatch, db_session):
    _, headers = await customer(monkeypatch, db_session)
    secret = "9876543210abc"
    for payload in (
        {"account_number": secret, "ifsc": IFSC},
        {"account_number": "123456789012", "ifsc": "bad-ifsc-value"},
        {"account_number": "123456789012", "ifsc": IFSC, "extra": "x"},
    ):
        response = client.post("/api/v1/bank-verifications", json=payload, headers=headers)
        assert response.status_code == 422
        assert secret not in response.text and "bad-ifsc-value" not in response.text
        assert "\"input\"" not in response.text


async def test_profile_name_required(monkeypatch, db_session):
    _, headers = await customer(monkeypatch, db_session, profile=False)
    assert verify(headers, acct("1234")).status_code == 400


# ----------------------------------------------------- outcomes and policy


@pytest.mark.parametrize(
    "tail,status,customer_status,code,visible",
    [
        ("0000", "FAILED", "FAILED", "ACCOUNT_NOT_FOUND", "ACCOUNT_NOT_FOUND"),
        ("2222", "FAILED", "FAILED", "NAME_MISMATCH", "NAME_MISMATCH"),
        ("3333", "MANUAL_REVIEW", "UNDER_REVIEW", "NAME_MATCH_PARTIAL", None),
        ("4444", "MANUAL_REVIEW", "UNDER_REVIEW", "NAME_MATCH_UNAVAILABLE", None),
    ],
)
async def test_outcome_policy(monkeypatch, db_session, tail, status, customer_status, code, visible):
    user, headers = await customer(monkeypatch, db_session)
    response = verify(headers, acct(tail))
    assert response.status_code == 200
    assert response.json()["status"] == customer_status
    assert response.json()["failure_code"] == visible
    (row,) = await rows_for(db_session, user.id)
    assert row.status == status and row.failure_code == code


async def test_failed_attempt_allows_retry_with_another_account(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    assert verify(headers, acct("0000")).json()["status"] == "FAILED"
    assert verify(headers, acct("5555")).json()["status"] == "VERIFIED"
    assert len(await rows_for(db_session, user.id)) == 2


async def test_provider_rejection_marks_failed(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    Dev.behaviour = "reject"
    response = verify(headers, acct("1234"))
    assert response.json()["status"] == "FAILED"
    assert response.json()["failure_code"] == "PROVIDER_REJECTED"


async def test_unknown_provider_failure_code_is_normalised(monkeypatch, db_session):
    from app.providers.bank_verification import BankVerificationResult

    user, headers = await customer(monkeypatch, db_session)
    original = Dev.verify

    async def odd(self, **kw):
        return BankVerificationResult("dev-bank-odd", "FAILED", failure_code="ARBITRARY free text 123")

    monkeypatch.setattr(Dev, "verify", odd)
    verify(headers, acct("1234"))
    (row,) = await rows_for(db_session, user.id)
    assert row.failure_code == "VERIFICATION_FAILED"
    monkeypatch.setattr(Dev, "verify", original)


# -------------------------------------------------- pending / timeout / sync


async def test_pending_then_sync_resolves(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    response = verify(headers, acct("1111"))
    assert response.json()["status"] == "PENDING"
    (row,) = await rows_for(db_session, user.id)
    assert row.status == "PENDING" and row.provider_ref

    from app.providers.bank_verification import BankVerificationResult

    Dev.records[row.provider_ref] = BankVerificationResult(
        row.provider_ref, "VERIFIED", name_match_result="MATCH", bank_name="Dev Test Bank"
    )
    counts = await build_bank_verification_service(db_session).sync_pending()
    await db_session.commit()
    assert counts["updated"] == 1
    (row,) = await rows_for(db_session, user.id)
    assert row.status == "VERIFIED"


async def test_unresolved_pending_goes_to_manual_review_after_timeout(
    monkeypatch, db_session
):
    user, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("1111"))
    real = bank_domain.utcnow
    monkeypatch.setattr(bank_domain, "utcnow", lambda: real() + timedelta(hours=48))
    counts = await build_bank_verification_service(db_session).sync_pending()
    await db_session.commit()
    assert counts["reviewed"] == 1
    (row,) = await rows_for(db_session, user.id)
    assert row.status == "MANUAL_REVIEW" and row.failure_code == "PROVIDER_UNRESOLVED"


async def test_timeout_keeps_initiated_and_retry_reuses_reference(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    Dev.behaviour = "timeout"
    response = verify(headers, acct("7777"))
    assert response.status_code == 503 and "Retry-After" in response.headers
    (row,) = await rows_for(db_session, user.id)
    assert row.status == "INITIATED" and row.provider_ref is None
    assert acct("7777") not in response.text
    reference, row_id = row.client_reference, row.id

    Dev.behaviour = "ok"
    retry = verify(headers, acct("7777"))
    assert retry.status_code == 200 and retry.json()["status"] == "VERIFIED"
    (row,) = await rows_for(db_session, user.id)
    assert row.id == row_id and row.client_reference == reference


async def test_sync_resumes_initiated_after_timeout(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    Dev.behaviour = "timeout"
    assert verify(headers, acct("7777")).status_code == 503
    Dev.behaviour = "ok"
    await build_bank_verification_service(db_session).sync_pending()
    await db_session.commit()
    (row,) = await rows_for(db_session, user.id)
    assert row.status == "VERIFIED"


async def test_initiated_past_expiry_goes_to_manual_review(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    Dev.behaviour = "timeout"
    verify(headers, acct("7777"))
    real = bank_domain.utcnow
    monkeypatch.setattr(bank_domain, "utcnow", lambda: real() + timedelta(hours=48))
    await build_bank_verification_service(db_session).sync_pending()
    await db_session.commit()
    (row,) = await rows_for(db_session, user.id)
    assert row.status == "MANUAL_REVIEW" and row.provider_ref is None


# -------------------------------------------------------------- idempotency


async def test_same_account_is_idempotent(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    first = verify(headers, acct("6789")).json()
    second = verify(headers, acct("6789")).json()
    assert first["id"] == second["id"]
    assert len(await rows_for(db_session, user.id)) == 1
    assert len(Dev.calls) == 1


async def test_other_account_while_in_flight_conflicts(monkeypatch, db_session):
    _, headers = await customer(monkeypatch, db_session)
    assert verify(headers, acct("1111")).json()["status"] == "PENDING"
    assert verify(headers, acct("5555")).status_code == 409
    assert verify(headers, acct("1111")).status_code == 200  # same account resumes


async def test_new_account_supersedes_previous_verified(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("5555"))
    verify(headers, acct("6666"))
    rows = await rows_for(db_session, user.id)
    assert [r.status for r in rows] == ["VERIFIED", "VERIFIED"]
    assert rows[0].superseded_at is not None and rows[1].superseded_at is None
    service = build_bank_verification_service(db_session)
    account = await service.reveal_verified_account(user_id=user.id, purpose="test")
    assert account.account_number == acct("6666")


async def test_attempt_limit_returns_429(monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "bank_verification_max_attempts_per_day", 2)
    _, headers = await customer(monkeypatch, db_session)
    assert verify(headers, acct("0000", "50100001")).status_code == 200
    assert verify(headers, acct("0000", "50100002")).status_code == 200
    limited = verify(headers, acct("0000", "50100003"))
    assert limited.status_code == 429 and "Retry-After" in limited.headers


async def test_account_shared_with_another_user_goes_to_review(monkeypatch, db_session):
    _, first_headers = await customer(monkeypatch, db_session)
    other, other_headers = await customer(monkeypatch, db_session)
    assert verify(first_headers, acct("8888")).json()["status"] == "VERIFIED"
    response = verify(other_headers, acct("8888"))
    assert response.json()["status"] == "UNDER_REVIEW"
    assert response.json()["failure_code"] is None  # fraud signal not revealed
    (row,) = await rows_for(db_session, other.id)
    assert row.failure_code == "ACCOUNT_SHARED_WITH_OTHER_USER"


# ----------------------------------------------------- customer authorization


async def test_customer_only_sees_own_verification(monkeypatch, db_session):
    _, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("6789"))
    _, other_headers = await customer(monkeypatch, db_session)
    assert client.get("/api/v1/bank-verifications/current", headers=other_headers).status_code == 404


async def test_unauthenticated_requests_rejected(monkeypatch, db_session):
    for response in (
        client.post("/api/v1/bank-verifications", json={"account_number": acct("1234"), "ifsc": IFSC}),
        client.get("/api/v1/bank-verifications/current"),
        client.get(f"/api/v1/admin/bank-verifications/{uuid4()}"),
        client.get(f"/api/v1/admin/bank-verifications/users/{uuid4()}"),
        client.post(f"/api/v1/admin/bank-verifications/{uuid4()}/resolve", json={}),
    ):
        assert response.status_code in (401, 403)


# ------------------------------------------------------------ admin access


async def review_case(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("3333"))
    (row,) = await rows_for(db_session, user.id)
    return user, headers, row.id


def admin_get(headers, vid):
    return client.get(f"/api/v1/admin/bank-verifications/{vid}", headers=headers)


async def test_admin_read_is_role_restricted_masked_and_audited(monkeypatch, db_session):
    user, _, vid = await review_case(monkeypatch, db_session)
    reviewer, reviewer_headers = await make_actor(monkeypatch, db_session, role="KYC_REVIEWER")
    _, support_headers = await make_actor(monkeypatch, db_session, role="CUSTOMER_SUPPORT")
    _, collections_headers = await make_actor(monkeypatch, db_session, role="COLLECTIONS_AGENT")
    _, plain_headers = await customer(monkeypatch, db_session)

    for denied in (support_headers, collections_headers, plain_headers):
        assert admin_get(denied, vid).status_code == 403
        assert client.get(
            f"/api/v1/admin/bank-verifications/users/{user.id}", headers=denied
        ).status_code == 403

    ok = admin_get(reviewer_headers, vid)
    assert ok.status_code == 200
    data = ok.json()
    assert data["account_number_masked"] == "XXXXXXXX3333"
    assert data["status"] == "MANUAL_REVIEW" and data["name_match_result"] == "PARTIAL"
    assert acct("3333") not in ok.text
    assert "account_number_encrypted" not in ok.text and "fingerprint" not in ok.text

    listing = client.get(f"/api/v1/admin/bank-verifications/users/{user.id}", headers=reviewer_headers)
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert acct("3333") not in listing.text

    actions = await audit_actions(db_session)
    assert "BANK_VERIFICATION_VIEWED" in actions and "BANK_VERIFICATION_LIST_VIEWED" in actions
    viewed = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "BANK_VERIFICATION_VIEWED")
        )
    ).scalars().first()
    assert viewed.actor_role == "KYC_REVIEWER" and viewed.entity_id == str(vid)
    # Denied reads are not recorded as views.
    assert actions.count("BANK_VERIFICATION_VIEWED") == 1


async def test_admin_unknown_verification_404(monkeypatch, db_session):
    _, headers = await make_actor(monkeypatch, db_session, role="KYC_REVIEWER")
    assert admin_get(headers, uuid4()).status_code == 404


def resolve(headers, vid, decision, reason="Verified manually against bank letter"):
    return client.post(
        f"/api/v1/admin/bank-verifications/{vid}/resolve",
        json={"decision": decision, "reason": reason},
        headers=headers,
    )


async def test_review_approval_verifies_and_is_audited(monkeypatch, db_session):
    user, headers, vid = await review_case(monkeypatch, db_session)
    admin, admin_headers = await make_actor(monkeypatch, db_session, role="FINANCE")
    response = resolve(admin_headers, vid, "VERIFIED")
    assert response.status_code == 200 and response.json()["status"] == "VERIFIED"
    assert client.get("/api/v1/bank-verifications/current", headers=headers).json()["status"] == "VERIFIED"
    (row,) = await rows_for(db_session, user.id)
    assert row.reviewed_by_admin_user_id is not None and row.reviewed_at is not None
    assert row.resolution_reason.startswith("Verified manually")
    log = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "BANK_VERIFICATION_RESOLVED")
        )
    ).scalar_one()
    assert log.old_value["status"] == "MANUAL_REVIEW" and log.new_value["status"] == "VERIFIED"
    assert log.reason and log.actor_role == "FINANCE"


async def test_review_rejection_fails_verification(monkeypatch, db_session):
    user, _, vid = await review_case(monkeypatch, db_session)
    _, admin_headers = await make_actor(monkeypatch, db_session, role="KYC_REVIEWER")
    response = resolve(admin_headers, vid, "FAILED", "Documents do not support this account")
    assert response.json()["status"] == "FAILED"
    assert response.json()["failure_code"] == "REVIEW_REJECTED"


async def test_review_resolution_is_permission_controlled(monkeypatch, db_session):
    _, _, vid = await review_case(monkeypatch, db_session)
    # AUDITOR and SENIOR_UNDERWRITER can read but not resolve.
    for role in ("AUDITOR", "SENIOR_UNDERWRITER", "CUSTOMER_SUPPORT"):
        _, headers = await make_actor(monkeypatch, db_session, role=role)
        assert resolve(headers, vid, "VERIFIED").status_code == 403
    _, plain_headers = await customer(monkeypatch, db_session)
    assert resolve(plain_headers, vid, "VERIFIED").status_code == 403
    assert admin_get((await make_actor(monkeypatch, db_session, role="AUDITOR"))[1], vid).status_code == 200


async def test_review_resolution_rules(monkeypatch, db_session):
    user, headers, vid = await review_case(monkeypatch, db_session)
    _, admin_headers = await make_actor(monkeypatch, db_session, role="KYC_REVIEWER")
    assert resolve(admin_headers, vid, "VERIFIED", "short").status_code == 400
    assert resolve(admin_headers, vid, "MAYBE").status_code == 400
    assert resolve(admin_headers, vid, "VERIFIED").status_code == 200
    # Already resolved: cannot be decided twice.
    assert resolve(admin_headers, vid, "FAILED").status_code == 409


async def test_admin_cannot_resolve_their_own_verification(monkeypatch, db_session):
    admin, admin_headers = await make_actor(monkeypatch, db_session, role="KYC_REVIEWER")
    db_session.add(UserProfile(user_id=admin.id, first_name="Ravi", last_name="Iyer"))
    await db_session.commit()
    verify(admin_headers, acct("3333"))
    (row,) = await rows_for(db_session, admin.id)
    assert resolve(admin_headers, row.id, "VERIFIED").status_code == 403


async def test_cannot_approve_without_provider_reference(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    Dev.behaviour = "timeout"
    verify(headers, acct("7777"))
    real = bank_domain.utcnow
    monkeypatch.setattr(bank_domain, "utcnow", lambda: real() + timedelta(hours=48))
    await build_bank_verification_service(db_session).sync_pending()
    await db_session.commit()
    (row,) = await rows_for(db_session, user.id)
    _, admin_headers = await make_actor(monkeypatch, db_session, role="KYC_REVIEWER")
    assert resolve(admin_headers, row.id, "VERIFIED").status_code == 409
    assert resolve(admin_headers, row.id, "FAILED").status_code == 200


# ---------------------------------------------------- internal sensitive access


async def test_reveal_is_audited_without_the_number(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    number = acct("6789")
    verify(headers, number)
    service = build_bank_verification_service(db_session)
    account = await service.reveal_verified_account(
        user_id=user.id, purpose="DISBURSEMENT", reference="loan-123"
    )
    await db_session.commit()
    assert account.account_number == number and account.account_last4 == "6789"
    assert number not in repr(account)
    blob = await audit_blob(db_session)
    assert "BANK_ACCOUNT_DECRYPTED" in await audit_actions(db_session)
    assert "DISBURSEMENT" in blob and number not in blob


async def test_reveal_requires_a_verified_account(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("3333"))  # under review, not verified
    from app.domain.bank_verification import BankVerificationNotFound

    with pytest.raises(BankVerificationNotFound):
        await build_bank_verification_service(db_session).reveal_verified_account(
            user_id=user.id, purpose="x"
        )


# --------------------------------------------------------------- encryption


async def test_unconfigured_encryption_fails_closed(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    monkeypatch.setattr(get_settings(), "field_encryption_keys", None)
    response = verify(headers, acct("6789"))
    assert response.status_code == 503
    assert acct("6789") not in response.text
    assert await rows_for(db_session, user.id) == []


async def test_missing_fingerprint_key_fails_closed(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    monkeypatch.setattr(get_settings(), "bank_fingerprint_key", None)
    assert verify(headers, acct("6789")).status_code == 503
    assert await rows_for(db_session, user.id) == []


async def test_key_rotation_reencrypts_and_old_data_still_readable(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    number = acct("6789")
    verify(headers, number)
    (before,) = await rows_for(db_session, user.id)
    old_token = before.account_number_encrypted

    monkeypatch.setattr(get_settings(), "field_encryption_active_key_id", "k2")
    service = build_bank_verification_service(db_session)
    # Old ciphertext remains readable while rotating.
    assert (await service.reveal_verified_account(user_id=user.id, purpose="t")).account_number == number
    assert await service.rotate_encryption() == 1
    await db_session.commit()
    (after,) = await rows_for(db_session, user.id)
    assert after.encryption_key_id == "k2" and after.account_number_encrypted.startswith("v1:k2:")
    assert after.account_number_encrypted != old_token
    assert (await service.reveal_verified_account(user_id=user.id, purpose="t")).account_number == number
    assert await service.rotate_encryption() == 0

    # Dropping the old key afterwards still works because data was rotated.
    monkeypatch.setattr(get_settings(), "field_encryption_keys", f"k2:{K2}")
    assert (await service.reveal_verified_account(user_id=user.id, purpose="t")).account_number == number


async def test_ciphertext_cannot_be_moved_to_another_record(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    other, other_headers = await customer(monkeypatch, db_session)
    verify(headers, acct("5555"))
    verify(other_headers, acct("6666"))
    (a,) = await rows_for(db_session, user.id)
    stolen = a.account_number_encrypted
    (b,) = await rows_for(db_session, other.id)
    victim_id = b.id
    await db_session.execute(
        text("UPDATE bank_account_verifications SET account_number_encrypted = :t WHERE id = :i"),
        {"t": stolen, "i": victim_id},
    )
    await db_session.commit()
    db_session.expire_all()  # raw SQL bypassed the identity map
    service = build_bank_verification_service(db_session)
    with pytest.raises(EncryptionError):
        await service.reveal_verified_account(user_id=other.id, purpose="t")


# --------------------------------------------------------- database guarantees


async def test_database_rejects_delete_and_binding_changes(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("6789"))
    (row,) = await rows_for(db_session, user.id)
    row_id = row.id
    for statement in (
        "DELETE FROM bank_account_verifications WHERE id = :id",
        "UPDATE bank_account_verifications SET account_last4 = '0000' WHERE id = :id",
        "UPDATE bank_account_verifications SET ifsc = 'ICIC0000001' WHERE id = :id",
        "UPDATE bank_account_verifications SET account_fingerprint = repeat('a', 64) WHERE id = :id",
        "UPDATE bank_account_verifications SET status = 'FAILED', verified_at = NULL WHERE id = :id",
        "UPDATE bank_account_verifications SET name_match_result = 'MISMATCH' WHERE id = :id",
        "UPDATE bank_account_verifications SET provider_ref = 'other' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(statement), {"id": row_id})
        await db_session.rollback()


async def test_database_allows_only_one_in_flight_per_user(monkeypatch, db_session):
    user, headers = await customer(monkeypatch, db_session)
    verify(headers, acct("1111"))  # PENDING
    (row,) = await rows_for(db_session, user.id)
    db_session.add(
        Row(
            user_id=user.id,
            status="INITIATED",
            account_number_encrypted="x",
            encryption_key_id="k1",
            account_last4="1234",
            account_fingerprint="a" * 64,
            ifsc=IFSC,
            provider="development",
            client_reference="dup",
            expires_at=row.expires_at,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


def test_development_provider_refused_in_production(monkeypatch):
    from app.providers.factory import get_bank_verification_provider

    monkeypatch.setattr(get_settings(), "environment", "production")
    with pytest.raises(RuntimeError):
        get_bank_verification_provider()


async def test_concurrent_identical_requests_create_one_verification(monkeypatch, db_session):
    from concurrent.futures import ThreadPoolExecutor

    user, headers = await customer(monkeypatch, db_session)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: verify(headers, acct("6789")), range(4)))
    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(await rows_for(db_session, user.id)) == 1
    assert len(Dev.calls) == 1
