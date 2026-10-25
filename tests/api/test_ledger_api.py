"""2.13 ledger tests on real Postgres: invariants are enforced by the database
itself, not just by service code."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.domain import ledger as L
from app.domain.ledger import LedgerConflict, LedgerNotFound, TxKind, UnbalancedTransaction
from app.main import app
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction
from app.providers.bank_verification_development import (
    DevelopmentBankVerificationProvider as DevBank,
)
from app.providers.disbursement_development import DevelopmentDisbursementProvider as Dev
from app.providers.esign_development import DevelopmentESignProvider as DevESign
from app.services.ledger_factory import build_ledger_service
from app.workers.disbursement import run_once
from tests.api.test_bank_verification_api import FP, K1, K2
from tests.api.test_disbursement_api import (  # noqa: F401
    SECRET as DISB_SECRET,
    create,
    current,
    hook,
    post_hook,
    ready,
)
from tests.api.test_esign_api import SIGNED_PDF  # noqa: F401
from tests.api.test_loan_offer_api import issued_offer, make_actor as _make_actor, world  # noqa: F401

client = TestClient(app)
D = Decimal


@pytest.fixture(autouse=True)
def env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "disbursement_webhook_secret", DISB_SECRET)
    monkeypatch.setattr(s, "esign_webhook_secret", "unit-test-webhook-secret")
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


async def make_actor(monkeypatch, db_session, *, role=None):
    row, headers = await _make_actor(monkeypatch, db_session, role=role)
    return SimpleNamespace(id=row.id), headers


async def disbursed(world, db_session, monkeypatch, behaviour="instant"):
    r = await ready(world, db_session, monkeypatch)
    Dev.behaviour = behaviour
    assert create(r.finance_headers, r.offer_id).status_code == 201
    await run_once()
    return r


async def count(db_session, model) -> int:
    db_session.expire_all()
    return (await db_session.execute(select(func.count()).select_from(model))).scalar_one()


async def post_pair(session_factory, r, *, key, amount="10.00", kind=TxKind.ADJUSTMENT, source=None):
    async with session_factory() as session:
        svc = build_ledger_service(session)
        tx = await svc.post(
            kind=kind,
            idempotency_key=key,
            source_type="test",
            source_id=source or uuid4(),
            loan_offer_id=r.offer_id,
            user_id=r.customer_id,
            lines=[L.debit(L.BANK, D(amount)), L.credit(L.UNAPPLIED_RECEIPTS, D(amount))],
            description="test posting",
        )
        await session.commit()
        return tx.id


# -------------------------------------------------------- seeded accounts


async def test_system_accounts_are_seeded_with_correct_sides(db_session):
    rows = (await db_session.execute(select(LedgerAccount))).scalars().all()
    by_code = {a.code: a for a in rows}
    assert set(L.SYSTEM_ACCOUNTS) <= set(by_code)
    for code, (_, kind) in L.SYSTEM_ACCOUNTS.items():
        assert by_code[code].account_type == kind.value
        assert by_code[code].normal_side == L.normal_side(kind.value).value
        assert by_code[code].is_active


async def test_accounts_cannot_be_deleted_or_retyped(db_session):
    with pytest.raises(DBAPIError):
        await db_session.execute(text("DELETE FROM ledger_accounts WHERE code = 'BANK_CLEARING'"))
    await db_session.rollback()
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE ledger_accounts SET account_type = 'LIABILITY' WHERE code = 'BANK_CLEARING'")
        )
    await db_session.rollback()
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE ledger_accounts SET code = 'X' WHERE code = 'BANK_CLEARING'")
        )
    await db_session.rollback()


# ------------------------------------------------------ debit/credit invariant


async def test_disbursement_posts_a_balanced_transaction(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    tx = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    entries = (
        await db_session.execute(select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id))
    ).scalars().all()
    debits = sum(e.amount for e in entries if e.direction == "DEBIT")
    credits = sum(e.amount for e in entries if e.direction == "CREDIT")
    assert debits == credits == D("5000.00") == tx.total_amount
    assert tx.entry_count == len(entries) == 2 and tx.kind == "DISBURSEMENT"
    assert str(tx.loan_offer_id) == r.offer_id


async def test_database_rejects_an_unbalanced_transaction(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    tx_id = uuid4()
    accounts = {
        a.code: a.id for a in (await db_session.execute(select(LedgerAccount))).scalars()
    }
    await db_session.execute(
        text(
            "INSERT INTO ledger_transactions (id, kind, idempotency_key, payload_hash, source_type, "
            "source_id, loan_offer_id, user_id, currency, description, entry_count, total_amount) "
            "VALUES (:id, 'ADJUSTMENT', :key, 'h', 't', :src, :offer, :user, 'INR', 'd', 2, 10.00)"
        ),
        dict(id=tx_id, key=f"k-{tx_id}", src=uuid4(), offer=r.offer_id, user=r.customer_id),
    )
    for n, (code, direction, amount) in enumerate(
        [(L.BANK, "DEBIT", "10.00"), (L.UNAPPLIED_RECEIPTS, "CREDIT", "9.99")], start=1
    ):
        await db_session.execute(
            text(
                "INSERT INTO ledger_entries (id, transaction_id, line_no, account_id, direction, amount) "
                "VALUES (:id, :tx, :n, :acct, :dir, :amt)"
            ),
            dict(id=uuid4(), tx=tx_id, n=n, acct=accounts[code], dir=direction, amt=amount),
        )
    with pytest.raises(DBAPIError, match="unbalanced"):
        await db_session.commit()
    await db_session.rollback()
    assert await count(db_session, LedgerTransaction) == 0


async def test_database_rejects_a_header_with_no_entries(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    tx_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO ledger_transactions (id, kind, idempotency_key, payload_hash, source_type, "
            "source_id, loan_offer_id, user_id, currency, description, entry_count, total_amount) "
            "VALUES (:id, 'ADJUSTMENT', :key, 'h', 't', :src, :offer, :user, 'INR', 'd', 2, 10.00)"
        ),
        dict(id=tx_id, key=f"k-{tx_id}", src=uuid4(), offer=r.offer_id, user=r.customer_id),
    )
    with pytest.raises(DBAPIError):
        await db_session.commit()
    await db_session.rollback()


async def test_entries_cannot_be_added_to_an_already_posted_transaction(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    tx = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    accounts = {a.code: a.id for a in (await db_session.execute(select(LedgerAccount))).scalars()}
    tx_id = tx.id
    # Even a perfectly balanced extra pair breaks the header's entry_count.
    for n, (code, direction) in enumerate([(L.BANK, "DEBIT"), (L.UNAPPLIED_RECEIPTS, "CREDIT")], start=3):
        await db_session.execute(
            text(
                "INSERT INTO ledger_entries (id, transaction_id, line_no, account_id, direction, amount) "
                "VALUES (:id, :tx, :n, :acct, :dir, 1.00)"
            ),
            dict(id=uuid4(), tx=tx_id, n=n, acct=accounts[code], dir=direction),
        )
    with pytest.raises(DBAPIError, match="do not match"):
        await db_session.commit()
    await db_session.rollback()


async def test_service_refuses_unbalanced_postings_before_touching_the_database(
    world, db_session, monkeypatch
):
    r = await ready(world, db_session, monkeypatch)
    svc = build_ledger_service(db_session)
    with pytest.raises(UnbalancedTransaction):
        await svc.post(
            kind=TxKind.ADJUSTMENT, idempotency_key="x1", source_type="t", source_id=uuid4(),
            loan_offer_id=r.offer_id, user_id=r.customer_id, description="bad",
            lines=[L.debit(L.BANK, D("5.00")), L.credit(L.UNAPPLIED_RECEIPTS, D("4.00"))],
        )
    assert await count(db_session, LedgerTransaction) == 0


async def test_unknown_and_inactive_accounts_are_refused(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    svc = build_ledger_service(db_session)
    kw = dict(kind=TxKind.ADJUSTMENT, source_type="t", source_id=uuid4(),
              loan_offer_id=r.offer_id, user_id=r.customer_id, description="d")
    with pytest.raises(LedgerNotFound):
        await svc.post(
            idempotency_key="nx", **kw,
            lines=[L.debit("NO_SUCH", D("1.00")), L.credit(L.BANK, D("1.00"))],
        )
    await db_session.execute(text("UPDATE ledger_accounts SET is_active = false WHERE code = 'FEE_INCOME'"))
    await db_session.commit()
    try:
        with pytest.raises(LedgerConflict):
            await svc.post(
                idempotency_key="in", **kw,
                lines=[L.debit(L.BANK, D("1.00")), L.credit(L.FEE_INCOME, D("1.00"))],
            )
    finally:
        await db_session.rollback()
        await db_session.execute(text("UPDATE ledger_accounts SET is_active = true WHERE code = 'FEE_INCOME'"))
        await db_session.commit()


# ------------------------------------------------------------- append-only


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ledger_entries SET amount = amount + 1",
        "DELETE FROM ledger_entries",
        "UPDATE ledger_transactions SET description = 'edited'",
        "DELETE FROM ledger_transactions",
    ],
)
async def test_history_cannot_be_edited_or_deleted(world, db_session, monkeypatch, sql):
    await disbursed(world, db_session, monkeypatch)
    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.execute(text(sql))
    await db_session.rollback()
    assert await count(db_session, LedgerEntry) == 2


# ------------------------------------------------------- duplicate posting


async def test_duplicate_posting_returns_the_original_and_adds_nothing(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    source = uuid4()
    first = await post_pair(AsyncSessionLocal, r, key="dup-1", source=source)
    again = await post_pair(AsyncSessionLocal, r, key="dup-1", source=source)
    assert first == again
    assert await count(db_session, LedgerTransaction) == 1
    assert await count(db_session, LedgerEntry) == 2


async def test_reusing_a_key_with_different_content_is_refused(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    await post_pair(AsyncSessionLocal, r, key="dup-2", amount="10.00")
    with pytest.raises(LedgerConflict):
        await post_pair(AsyncSessionLocal, r, key="dup-2", amount="11.00")
    assert await count(db_session, LedgerTransaction) == 1


async def test_concurrent_postings_with_one_key_create_exactly_one_transaction(
    world, db_session, monkeypatch
):
    r = await ready(world, db_session, monkeypatch)
    source = uuid4()
    ids = await asyncio.gather(
        *[post_pair(AsyncSessionLocal, r, key="race-1", source=source) for _ in range(10)]
    )
    assert len(set(ids)) == 1
    assert await count(db_session, LedgerTransaction) == 1
    assert await count(db_session, LedgerEntry) == 2


async def test_concurrent_postings_with_different_keys_all_land_and_balance(
    world, db_session, monkeypatch
):
    r = await ready(world, db_session, monkeypatch)
    await asyncio.gather(
        *[post_pair(AsyncSessionLocal, r, key=f"many-{i}", amount=f"{i + 1}.00") for i in range(8)]
    )
    assert await count(db_session, LedgerTransaction) == 8
    svc = build_ledger_service(db_session)
    balances = {b.code: b for b in await svc.balances()}
    assert balances[L.BANK].debit_total == balances[L.UNAPPLIED_RECEIPTS].credit_total == D("36.00")


# ------------------------------------------------------------------ rollback


async def test_a_rolled_back_posting_leaves_no_trace(world, db_session, monkeypatch):
    r = await ready(world, db_session, monkeypatch)
    async with AsyncSessionLocal() as session:
        svc = build_ledger_service(session)
        await svc.post(
            kind=TxKind.ADJUSTMENT, idempotency_key="rb-1", source_type="t", source_id=uuid4(),
            loan_offer_id=r.offer_id, user_id=r.customer_id, description="d",
            lines=[L.debit(L.BANK, D("5.00")), L.credit(L.UNAPPLIED_RECEIPTS, D("5.00"))],
        )
        await session.rollback()
    assert await count(db_session, LedgerTransaction) == 0
    assert await count(db_session, LedgerEntry) == 0
    # ...and the key is free to use again afterwards.
    await post_pair(AsyncSessionLocal, r, key="rb-1", amount="5.00")
    assert await count(db_session, LedgerTransaction) == 1


async def test_disbursement_success_rolls_back_if_the_ledger_cannot_post(
    world, db_session, monkeypatch
):
    from app.services.ledger import LedgerService

    r = await ready(world, db_session, monkeypatch)
    Dev.behaviour = "ok"
    assert create(r.finance_headers, r.offer_id).status_code == 201
    await run_once()
    d = await current(db_session, r.offer_id)
    assert d.status == "PROCESSING"
    ref = d.provider_ref

    async def boom(self, d):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(LedgerService, "post_disbursement", boom)
    body, headers = hook(ref, "SUCCESS", utr="UTR1")
    with pytest.raises(RuntimeError):
        post_hook(body, headers)
    d = await current(db_session, r.offer_id)
    # Money state and books move together or not at all.
    assert d.status == "PROCESSING" and d.completed_at is None
    assert await count(db_session, LedgerTransaction) == 0


# ------------------------------------------------------------------ reversal


async def test_reversal_is_an_exact_mirror_that_nets_to_zero(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    svc = build_ledger_service(db_session)
    original = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    reversal = await svc.reverse(
        original_transaction_id=original.id,
        idempotency_key="rev-1",
        source_type="t",
        source_id=uuid4(),
        reason="test",
    )
    await db_session.commit()
    assert reversal.kind == "DISBURSEMENT_REVERSAL"
    assert reversal.reverses_transaction_id == original.id
    assert reversal.total_amount == original.total_amount
    balances = {b.code: b for b in await svc.balances()}
    assert balances[L.LOAN_PRINCIPAL].balance == 0 and balances[L.BANK].balance == 0
    # History kept: both transactions still exist, nothing was edited.
    assert await count(db_session, LedgerTransaction) == 2
    assert await svc.principal_outstanding(r.offer_id) == 0


async def test_reversing_twice_returns_the_same_reversal(world, db_session, monkeypatch):
    await disbursed(world, db_session, monkeypatch)
    svc = build_ledger_service(db_session)
    original = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    kw = dict(original_transaction_id=original.id, source_type="t", source_id=uuid4(), reason="r")
    a = await svc.reverse(idempotency_key="rev-a", **kw)
    b = await svc.reverse(idempotency_key="rev-b", **kw)  # different key, same original
    await db_session.commit()
    assert a.id == b.id
    assert await count(db_session, LedgerTransaction) == 2


async def test_a_reversal_cannot_itself_be_reversed(world, db_session, monkeypatch):
    await disbursed(world, db_session, monkeypatch)
    svc = build_ledger_service(db_session)
    original = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    rev = await svc.reverse(
        original_transaction_id=original.id, idempotency_key="r1", source_type="t",
        source_id=uuid4(), reason="r",
    )
    with pytest.raises(LedgerConflict):
        await svc.reverse(
            original_transaction_id=rev.id, idempotency_key="r2", source_type="t",
            source_id=uuid4(), reason="r",
        )
    with pytest.raises(LedgerNotFound):
        await svc.reverse(
            original_transaction_id=uuid4(), idempotency_key="r3", source_type="t",
            source_id=uuid4(), reason="r",
        )


async def test_database_allows_at_most_one_reversal_per_transaction(world, db_session, monkeypatch):
    await disbursed(world, db_session, monkeypatch)
    svc = build_ledger_service(db_session)
    original = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    await svc.reverse(
        original_transaction_id=original.id, idempotency_key="u1", source_type="t",
        source_id=uuid4(), reason="r",
    )
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO ledger_transactions (id, kind, idempotency_key, payload_hash, source_type, "
                "source_id, loan_offer_id, user_id, currency, description, entry_count, total_amount, "
                "reverses_transaction_id) SELECT gen_random_uuid(), 'DISBURSEMENT_REVERSAL', 'dup-rev', "
                "'h', 't', source_id, loan_offer_id, user_id, 'INR', 'd', entry_count, total_amount, id "
                "FROM ledger_transactions WHERE id = :id"
            ),
            dict(id=original.id),
        )
    await db_session.rollback()


async def test_concurrent_reversals_create_exactly_one(world, db_session, monkeypatch):
    await disbursed(world, db_session, monkeypatch)
    original = (await db_session.execute(select(LedgerTransaction))).scalars().one()
    original_id = original.id

    async def one(i):
        async with AsyncSessionLocal() as session:
            svc = build_ledger_service(session)
            tx = await svc.reverse(
                original_transaction_id=original_id, idempotency_key=f"conc-rev-{i}",
                source_type="t", source_id=uuid4(), reason="r",
            )
            await session.commit()
            return tx.id

    ids = await asyncio.gather(*[one(i) for i in range(6)])
    assert len(set(ids)) == 1
    assert await count(db_session, LedgerTransaction) == 2
    db_session.expire_all()
    svc = build_ledger_service(db_session)
    balances = {b.code: b for b in await svc.balances()}
    assert balances[L.LOAN_PRINCIPAL].balance == 0 and balances[L.BANK].balance == 0


# ------------------------------------------- disbursement <-> ledger wiring


async def test_disbursement_success_then_reversal_posts_and_mirrors(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch, behaviour="ok")
    ref = (await current(db_session, r.offer_id)).provider_ref
    assert await count(db_session, LedgerTransaction) == 0  # still PROCESSING: nothing booked

    body, headers = hook(ref, "SUCCESS", utr="UTR9")
    assert post_hook(body, headers).json()["outcome"] == "SUCCESS"
    svc = build_ledger_service(db_session)
    assert await svc.principal_outstanding(r.offer_id) == D("5000.00")

    body, headers = hook(ref, "REVERSED")
    assert post_hook(body, headers).json()["outcome"] == "REVERSED"
    db_session.expire_all()
    assert await svc.principal_outstanding(r.offer_id) == 0
    kinds = sorted(
        (await db_session.execute(select(LedgerTransaction.kind))).scalars().all()
    )
    assert kinds == ["DISBURSEMENT", "DISBURSEMENT_REVERSAL"]


async def test_duplicate_disbursement_webhooks_book_once(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch, behaviour="ok")
    ref = (await current(db_session, r.offer_id)).provider_ref
    body, headers = hook(ref, "SUCCESS", event_id="same-event")
    assert post_hook(body, headers).json()["outcome"] == "SUCCESS"
    assert post_hook(body, headers).json()["outcome"] == "DUPLICATE"
    body2, headers2 = hook(ref, "SUCCESS")  # new event id, same fact
    assert post_hook(body2, headers2).json()["outcome"] == "DUPLICATE_SUCCESS"
    assert await count(db_session, LedgerTransaction) == 1


async def test_instant_reversal_in_one_report_books_both_legs(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch, behaviour="ok")
    ref = (await current(db_session, r.offer_id)).provider_ref
    body, headers = hook(ref, "REVERSED", utr="U1")
    assert post_hook(body, headers).json()["outcome"] == "REVERSED"
    assert await count(db_session, LedgerTransaction) == 2


# ------------------------------------------------------------- admin reads


async def test_trial_balance_is_derived_balanced_and_role_restricted(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    auditor, auditor_headers = await make_actor(monkeypatch, db_session, role="AUDITOR")
    response = client.get("/api/v1/admin/ledger/trial-balance", headers=r.finance_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["balanced"] is True and body["total_debits"] == body["total_credits"]
    accounts = {a["code"]: a for a in body["accounts"]}
    assert accounts["LOAN_PRINCIPAL_RECEIVABLE"]["balance"] == "5000.00"
    assert accounts["BANK_CLEARING"]["balance"] == "-5000.00"  # cash out of the bank

    assert client.get("/api/v1/admin/ledger/trial-balance", headers=auditor_headers).status_code == 200
    # Underwriters have no ledger permission; customers are not admins at all.
    assert client.get("/api/v1/admin/ledger/trial-balance", headers=world.admin_headers).status_code == 403
    assert client.get("/api/v1/admin/ledger/trial-balance", headers=world.customer_headers).status_code == 403
    assert client.get("/api/v1/admin/ledger/trial-balance").status_code in (401, 403)

    per_loan = client.get(
        f"/api/v1/admin/ledger/trial-balance?loan_offer_id={r.offer_id}", headers=r.finance_headers
    ).json()
    assert per_loan["balanced"] is True


async def test_transaction_listing_and_detail(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    listed = client.get(
        f"/api/v1/admin/ledger/transactions?loan_offer_id={r.offer_id}", headers=r.finance_headers
    )
    assert listed.status_code == 200 and len(listed.json()) == 1
    tx_id = listed.json()[0]["id"]
    detail = client.get(f"/api/v1/admin/ledger/transactions/{tx_id}", headers=r.finance_headers)
    assert detail.status_code == 200
    entries = detail.json()["entries"]
    assert [(e["account_code"], e["direction"], e["amount"]) for e in entries] == [
        ("LOAN_PRINCIPAL_RECEIVABLE", "DEBIT", "5000.00"),
        ("BANK_CLEARING", "CREDIT", "5000.00"),
    ]
    assert client.get(f"/api/v1/admin/ledger/transactions/{uuid4()}", headers=r.finance_headers).status_code == 404


async def test_there_is_no_endpoint_that_writes_or_edits_the_ledger(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    for method in ("post", "put", "patch", "delete"):
        for path in ("/api/v1/admin/ledger/transactions", "/api/v1/admin/ledger/trial-balance"):
            response = getattr(client, method)(path, headers=r.finance_headers)
            assert response.status_code in (404, 405), (method, path, response.status_code)
