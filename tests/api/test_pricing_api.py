"""Pricing (KreditBee format): versions, maker-checker, offer snapshot,
net payout, ledger and EMI schedule, against real Postgres."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.domain import ledger as L
from app.domain.repayment import today_ist
from app.main import app
from app.models.disbursement import Disbursement
from app.models.ledger import LedgerTransaction
from app.models.pricing import LoanOfferPricing, PricingVersion
from app.services.ledger_factory import build_ledger_service
from tests.api import test_loan_offer_api as loan_offer_tests
from tests.api.test_disbursement_api import ready  # noqa: F401
from tests.api.test_loan_offer_api import world  # noqa: F401
from tests.api.test_repayment_api import (  # noqa: F401
    active_loan,
    count,
    disbursed,
    env,
    installments,
    make_actor,
    make_schedule,
    row,
    schedule_url,
    settle,
    started,
)

client = TestClient(app)
D = Decimal
BASE = "/api/v1/admin/pricing"


def body(**extra):
    return {
        "effective_from": today_ist().isoformat(),
        "annual_interest_percent": "36",
        "processing_fee_percent": "6",
        "gst_percent": "18",
        **extra,
    }


def new_version(headers, **extra):
    return client.post(f"{BASE}/versions", json=body(**extra), headers=headers)


async def approved_pricing(monkeypatch, db_session, **extra):
    """FINANCE makes it, a different SUPER_ADMIN approves it."""
    monkeypatch.setattr(get_settings(), "ledger_interest_fee_posting_enabled", True)
    _, maker = await make_actor(monkeypatch, db_session, role="FINANCE")
    _, checker = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    created = new_version(maker, **extra)
    assert created.status_code == 201, created.text
    approved = client.post(f"{BASE}/versions/{created.json()['id']}/approve", headers=checker)
    assert approved.status_code == 200, approved.text
    return approved.json(), maker, checker


def priced_terms(monkeypatch, tenure_days=90):
    def draft(application_id, principal="5000.00"):
        return {
            "loan_application_id": application_id,
            "principal_amount": principal,
            "tenure_days": tenure_days,
            "commercial_terms": {"note": "welcome"},
        }

    monkeypatch.setattr(loan_offer_tests, "draft_body", draft)


async def snapshot(db_session, offer_id):
    db_session.expire_all()
    return (
        await db_session.execute(
            select(LoanOfferPricing).where(LoanOfferPricing.loan_offer_id == offer_id)
        )
    ).scalar_one_or_none()


# ======================================================================
# Versions and maker-checker
# ======================================================================


async def test_maker_checker_lifecycle(monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "ledger_interest_fee_posting_enabled", True)
    _, maker = await make_actor(monkeypatch, db_session, role="FINANCE")
    _, checker = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    _, other_super = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")

    created = new_version(maker)
    assert created.status_code == 201, created.text
    v = created.json()
    assert v["status"] == "DRAFT" and v["version"] == 1
    assert v["late_charges_enabled"] is False  # OFF until the lender approves
    assert (D(v["bounce_percent"]), D(v["bounce_cap_amount"]), D(v["penal_annual_percent"])) == (
        D("4"), D("500"), D("36"),
    )
    assert v["penal_max_days"] == 180 and D(v["late_total_cap_percent_of_due"]) == D("40")

    # the maker cannot approve: FINANCE has no approve permission at all
    assert client.post(f"{BASE}/versions/{v['id']}/approve", headers=maker).status_code == 403
    # a draft is not in force yet
    assert client.get(f"{BASE}/current", headers=checker).json() is None

    ok = client.post(f"{BASE}/versions/{v['id']}/approve", headers=checker)
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    assert client.get(f"{BASE}/current", headers=checker).json()["id"] == v["id"]
    # decided once: approve/reject again conflicts
    assert client.post(f"{BASE}/versions/{v['id']}/approve", headers=other_super).status_code == 409
    assert (
        client.post(f"{BASE}/versions/{v['id']}/reject", json={"reason": "x"}, headers=other_super).status_code
        == 409
    )

    second = new_version(maker, annual_interest_percent="30")
    assert second.json()["version"] == 2
    rejected = client.post(
        f"{BASE}/versions/{second.json()['id']}/reject", json={"reason": "too low"}, headers=checker
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert rejected.json()["reject_reason"] == "too low"
    assert [x["version"] for x in client.get(f"{BASE}/versions", headers=checker).json()] == [2, 1]
    # a rejected version never becomes current
    assert client.get(f"{BASE}/current", headers=checker).json()["id"] == v["id"]


async def test_an_admin_cannot_approve_their_own_version(monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "ledger_interest_fee_posting_enabled", True)
    _, boss = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    created = new_version(boss)
    assert created.status_code == 201
    mine = client.post(f"{BASE}/versions/{created.json()['id']}/approve", headers=boss)
    assert mine.status_code == 403
    assert "created it" in mine.text or "permissions" in mine.text
    assert client.get(f"{BASE}/versions/{created.json()['id']}", headers=boss).json()["status"] == "DRAFT"


async def test_the_database_itself_refuses_self_approval(monkeypatch, db_session):
    monkeypatch.setattr(get_settings(), "ledger_interest_fee_posting_enabled", True)
    _, boss = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    created = new_version(boss).json()
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "UPDATE pricing_versions SET status='APPROVED', decided_at=now(), "
                "approved_by_admin_user_id = created_by_admin_user_id WHERE id = :i"
            ),
            {"i": created["id"]},
        )
    await db_session.rollback()


async def test_activation_is_refused_until_accounting_rules_are_enabled(monkeypatch, db_session):
    _, maker = await make_actor(monkeypatch, db_session, role="FINANCE")
    _, checker = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    v = new_version(maker).json()
    blocked = client.post(f"{BASE}/versions/{v['id']}/approve", headers=checker)
    assert blocked.status_code == 409 and "accounting rules" in blocked.text
    assert client.get(f"{BASE}/versions/{v['id']}", headers=checker).json()["status"] == "DRAFT"


async def test_a_past_effective_date_is_refused(monkeypatch, db_session):
    from datetime import timedelta

    _, maker = await make_actor(monkeypatch, db_session, role="FINANCE")
    yesterday = (today_ist() - timedelta(days=1)).isoformat()
    assert new_version(maker, effective_from=yesterday).status_code == 400


async def test_future_version_is_not_current_until_its_date(monkeypatch, db_session):
    from datetime import timedelta

    tomorrow = (today_ist() + timedelta(days=1)).isoformat()
    v, _, checker = await approved_pricing(monkeypatch, db_session, effective_from=tomorrow)
    assert v["status"] == "APPROVED"
    assert client.get(f"{BASE}/current", headers=checker).json() is None


@pytest.mark.parametrize(
    "bad",
    [
        {"annual_interest_percent": "-1"},
        {"annual_interest_percent": "101"},
        {"processing_fee_percent": "26"},
        {"gst_percent": "51"},
        {"penal_max_days": 0},
        {"late_total_cap_percent_of_due": "0"},
        {"bounce_cap_amount": "-5"},
        {"surprise": 1},
    ],
)
async def test_bad_pricing_is_rejected(monkeypatch, db_session, bad):
    _, maker = await make_actor(monkeypatch, db_session, role="FINANCE")
    assert new_version(maker, **bad).status_code == 422
    assert await count(db_session, PricingVersion) == 0


async def test_only_authorised_admins_can_use_pricing(monkeypatch, db_session):
    _, reader = await make_actor(monkeypatch, db_session, role="READ_ONLY")
    _, auditor = await make_actor(monkeypatch, db_session, role="AUDITOR")
    _, customer = await make_actor(monkeypatch, db_session)
    assert new_version(reader).status_code == 403
    assert client.get(f"{BASE}/versions", headers=reader).status_code == 403
    assert client.get(f"{BASE}/versions", headers=auditor).status_code == 200  # read-only
    assert new_version(auditor).status_code == 403
    assert client.get(f"{BASE}/versions", headers=customer).status_code in (401, 403)
    assert new_version({}).status_code in (401, 403)


async def test_decided_versions_cannot_be_edited_or_deleted(monkeypatch, db_session):
    v, maker, _ = await approved_pricing(monkeypatch, db_session)
    for sql in (
        "UPDATE pricing_versions SET annual_interest_percent = 1",
        "UPDATE pricing_versions SET status = 'REJECTED', reject_reason='x'",
        "DELETE FROM pricing_versions",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()
    # even a draft's terms cannot be edited (a new version is required)
    d = new_version(maker, annual_interest_percent="20").json()
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE pricing_versions SET processing_fee_percent = 1 WHERE id = :i"), {"i": d["id"]}
        )
    await db_session.rollback()


# ======================================================================
# Offers freeze the price
# ======================================================================


async def test_offer_without_approved_pricing_is_unchanged(world, monkeypatch, db_session):
    offer = await loan_offer_tests.issued_offer(world)
    assert await snapshot(db_session, offer["id"]) is None
    assert offer["commercial_terms"] == {"interest_rate": "12", "processing_fee": "100"}


async def test_offer_freezes_the_pricing_it_was_made_under(world, monkeypatch, db_session):
    await approved_pricing(monkeypatch, db_session)
    priced_terms(monkeypatch)
    offer = await loan_offer_tests.issued_offer(world)
    s = await snapshot(db_session, offer["id"])
    assert (s.principal, s.processing_fee, s.gst_amount, s.net_payout) == (
        D("5000.00"), D("300.00"), D("54.00"), D("4646.00"),
    )
    assert (s.months, s.emi_amount, s.total_interest, s.total_repayable) == (
        3, D("1767.65"), D("302.96"), D("5302.96"),
    )
    assert D("82.9") < s.apr_percent < D("83.1")
    assert s.late_charges_enabled is False
    t = offer["commercial_terms"]
    assert t["net_disbursal_amount"] == "4646.00" and t["emi_amount"] == "1767.65"
    assert t["processing_fee_amount"] == "300.00" and t["gst_amount"] == "54.00"
    assert t["number_of_emis"] == "3" and t["interest_rate_percent_per_annum"] == "36"
    assert t["note"] == "welcome"  # harmless admin notes survive
    assert "No late" in t["late_payment_charges"]
    # the frozen snapshot can never change
    for sql in ("UPDATE loan_offer_pricing SET net_payout = net_payout + 1", "DELETE FROM loan_offer_pricing"):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()


async def test_a_later_price_change_never_reprices_an_existing_offer(world, monkeypatch, db_session):
    await approved_pricing(monkeypatch, db_session)
    priced_terms(monkeypatch)
    offer = await loan_offer_tests.issued_offer(world)
    # a cheaper version becomes current afterwards
    _, maker = await make_actor(monkeypatch, db_session, role="FINANCE")
    _, checker = await make_actor(monkeypatch, db_session, role="SUPER_ADMIN")
    v2 = new_version(maker, annual_interest_percent="24", processing_fee_percent="4").json()
    assert client.post(f"{BASE}/versions/{v2['id']}/approve", headers=checker).status_code == 200
    s = await snapshot(db_session, offer["id"])
    assert s.annual_interest_percent == D("36") and s.net_payout == D("4646.00")
    current = client.get(f"{BASE}/current", headers=checker).json()
    assert current["id"] == v2["id"]  # newest effective version wins for NEW offers


async def test_admins_cannot_type_price_terms_when_pricing_applies(world, monkeypatch, db_session):
    await approved_pricing(monkeypatch, db_session)
    for key in ("processing_fee", "interest_rate", "net_disbursal_amount", "emi_amount", "apr"):
        def draft(application_id, principal="5000.00", key=key):
            return {
                "loan_application_id": application_id,
                "principal_amount": principal,
                "tenure_days": 90,
                "commercial_terms": {key: "1"},
            }

        monkeypatch.setattr(loan_offer_tests, "draft_body", draft)
        r = client.post(
            "/api/v1/admin/loan-offers",
            json=draft(world.application["id"]),
            headers=world.admin_headers,
        )
        assert r.status_code == 400 and key in r.text
    assert await count(db_session, LoanOfferPricing) == 0


async def test_priced_loans_need_whole_thirty_day_months(world, monkeypatch, db_session):
    await approved_pricing(monkeypatch, db_session)
    priced_terms(monkeypatch, tenure_days=45)
    r = client.post(
        "/api/v1/admin/loan-offers",
        json=loan_offer_tests.draft_body(world.application["id"]),
        headers=world.admin_headers,
    )
    assert r.status_code == 400 and "30-day months" in r.text


async def test_pricing_fails_closed_if_accounting_rules_are_switched_off(world, monkeypatch, db_session):
    await approved_pricing(monkeypatch, db_session)
    priced_terms(monkeypatch)
    monkeypatch.setattr(get_settings(), "ledger_interest_fee_posting_enabled", False)
    r = client.post(
        "/api/v1/admin/loan-offers",
        json=loan_offer_tests.draft_body(world.application["id"]),
        headers=world.admin_headers,
    )
    assert r.status_code in (400, 409), r.text
    assert await count(db_session, LoanOfferPricing) == 0


# ======================================================================
# Payout, ledger, schedule
# ======================================================================


async def priced_loan(world, db_session, monkeypatch, months=3):
    await approved_pricing(monkeypatch, db_session)
    priced_terms(monkeypatch, tenure_days=30 * months)
    return await disbursed(world, db_session, monkeypatch)


async def test_payout_is_net_of_fee_and_gst_and_the_ledger_balances(world, db_session, monkeypatch):
    r = await priced_loan(world, db_session, monkeypatch)
    d = (await db_session.execute(select(Disbursement).where(Disbursement.loan_offer_id == r.offer_id))).scalar_one()
    assert d.amount == D("4646.00") and d.status == "SUCCESS"
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.LOAN_PRINCIPAL].balance == D("5000.00")  # customer owes the full principal
    assert balances[L.BANK].credit_total == D("4646.00")  # but only this left the bank
    assert balances[L.FEE_INCOME].balance == D("300.00")
    assert balances[L.GST_PAYABLE].balance == D("54.00")  # a liability, never income
    assert balances[L.GST_PAYABLE].account_type == "LIABILITY"
    tx = (await db_session.execute(select(LoanOfferPricing))).scalar_one()
    assert tx.net_payout == d.amount


async def test_a_reversed_payout_reverses_fee_and_gst_too(world, db_session, monkeypatch):
    r = await priced_loan(world, db_session, monkeypatch)
    d = (await db_session.execute(select(Disbursement).where(Disbursement.loan_offer_id == r.offer_id))).scalar_one()
    ledger = build_ledger_service(db_session)
    assert await ledger.reverse_disbursement(d) is not None
    await db_session.commit()
    balances = await build_ledger_service(db_session).balances()
    assert all(b.balance == 0 for b in balances)
    assert await count(db_session, LedgerTransaction) == 2


async def test_schedule_is_the_offers_emi_plan_and_cannot_be_overridden(world, db_session, monkeypatch):
    r = await priced_loan(world, db_session, monkeypatch)
    # the request cannot change what the offer fixed
    assert make_schedule(r, 2).status_code == 409
    assert make_schedule(r, 3, interval_days=15).status_code == 409
    created = client.post(schedule_url(), json={"loan_offer_id": r.offer_id}, headers=r.finance_headers)
    assert created.status_code == 201, created.text
    s = created.json()
    assert (s["principal_total"], s["interest_total"], s["total_payable"]) == ("5000.00", "302.96", "5302.96")
    assert s["installment_count"] == 3 and s["interval_days"] == 30
    rows = await installments(db_session, s["id"])
    assert [(i.principal_due, i.interest_due) for i in rows] == [
        (D("1617.65"), D("150.00")), (D("1666.18"), D("101.47")), (D("1716.17"), D("51.49")),
    ]
    assert client.get(schedule_url(f"/{s['id']}"), headers=r.finance_headers).json()["ledger_matches_schedule"] is True


async def test_paying_every_emi_clears_principal_and_books_interest(world, db_session, monkeypatch):
    r = await priced_loan(world, db_session, monkeypatch)
    sid = client.post(schedule_url(), json={"loan_offer_id": r.offer_id}, headers=r.finance_headers).json()["id"]
    assert client.post(schedule_url(f"/{sid}/activate"), headers=r.finance_headers).status_code == 200
    for amount in ("1767.65", "1767.65", "1767.66"):
        pid, ref = await started(world, r, amount, db_session)
        assert settle(ref, "SUCCESS", amount=amount) == "SUCCESS"
        assert (await row(db_session, pid)).unapplied_amount == 0
    rows = await installments(db_session, sid)
    assert all(i.status == "PAID" for i in rows)
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.LOAN_PRINCIPAL].balance == 0
    assert balances[L.INTEREST_INCOME].balance == D("302.96")
    assert balances[L.FEE_INCOME].balance == D("300.00") and balances[L.GST_PAYABLE].balance == D("54.00")
    assert balances[L.UNAPPLIED_RECEIPTS].balance == 0
    # cash in (5302.96) - cash out (4646) = fee + GST + interest = 656.96
    assert balances[L.BANK].balance == D("656.96")
    assert client.get(schedule_url(f"/{sid}"), headers=r.finance_headers).json()["ledger_matches_schedule"] is True


async def test_unpriced_loans_still_use_the_old_schedule_rules(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)  # no approved pricing
    d = (await db_session.execute(select(Disbursement).where(Disbursement.loan_offer_id == r.offer_id))).scalar_one()
    assert d.amount == D("5000.00")
    assert make_schedule(r, 2).status_code == 201
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert L.GST_PAYABLE not in {c for c, b in balances.items() if b.balance != 0}
