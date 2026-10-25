"""KreditBee-format late charges on priced loans (real Postgres)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.domain import ledger as L
from app.main import app
from app.models.late_charge import LateChargeAssessment
from app.models.repayment import RepaymentInstallment, RepaymentSchedule
from app.services.late_charges_factory import build_late_charge_service
from app.services.ledger_factory import build_ledger_service
from app.workers.repayment import run_once as run_repayments
import app.services.late_charges as late_service
from tests.api import test_loan_offer_api as loan_offer_tests
from tests.api.test_disbursement_api import ready  # noqa: F401
from tests.api.test_loan_offer_api import world  # noqa: F401
from tests.api.test_pricing_api import approved_pricing, priced_terms
from tests.api.test_repayment_api import (  # noqa: F401
    count,
    disbursed,
    env,
    installments,
    my_schedule,
    pay,
    row,
    schedule_url,
    settle,
    started,
)

client = TestClient(app)
D = Decimal


async def charged_loan(world, db_session, monkeypatch, *, late=True, **pricing):
    await approved_pricing(monkeypatch, db_session, late_charges_enabled=late, **pricing)
    priced_terms(monkeypatch, tenure_days=90)
    r = await disbursed(world, db_session, monkeypatch)
    sid = client.post(schedule_url(), json={"loan_offer_id": r.offer_id}, headers=r.finance_headers).json()["id"]
    assert client.post(schedule_url(f"/{sid}/activate"), headers=r.finance_headers).status_code == 200
    r.schedule_id = sid
    rows = await installments(db_session, sid)
    r.due1 = rows[0].due_date
    return r


async def assess(db_session, schedule_id, today):
    result = await build_late_charge_service(db_session).assess_schedule(schedule_id, today=today)
    await db_session.commit()
    return result


async def inst(db_session, schedule_id, n=0):
    return (await installments(db_session, schedule_id))[n]


async def test_nothing_is_charged_on_or_before_the_due_date(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    for today in (r.due1 - timedelta(days=3), r.due1):
        assert (await assess(db_session, r.schedule_id, today)).charges == 0
    assert await count(db_session, LateChargeAssessment) == 0


async def test_day_one_bounce_then_daily_penal_on_overdue_principal(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    res = await assess(db_session, r.schedule_id, r.due1 + timedelta(days=1))
    assert (res.charges, res.total) == (1, D("64.71"))  # 4% of 1,617.65 (below the Rs 500 cap)
    one = await inst(db_session, r.schedule_id)
    assert one.fee_due == D("64.71")
    # later days add penal charges; the first installment only
    res = await assess(db_session, r.schedule_id, r.due1 + timedelta(days=10))
    assert res.charges == 9
    one = await inst(db_session, r.schedule_id)
    assert D("79.00") < one.fee_due < D("79.20")  # ~KreditBee's 79.07 for 10 days
    others = (await installments(db_session, r.schedule_id))[1:]
    assert all(i.fee_due == 0 for i in others)  # not yet due: not charged
    kinds = [c.kind for c in (await db_session.execute(select(LateChargeAssessment).order_by(LateChargeAssessment.charge_date))).scalars()]
    assert kinds == ["BOUNCE"] + ["PENAL"] * 9


async def test_running_it_again_or_twice_never_double_charges(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    today = r.due1 + timedelta(days=5)
    first = await assess(db_session, r.schedule_id, today)
    again = await assess(db_session, r.schedule_id, today)
    assert first.charges == 5 and again.charges == 0
    assert await count(db_session, LateChargeAssessment) == 5
    # the database also refuses a second charge for the same installment and day
    one = await inst(db_session, r.schedule_id)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "INSERT INTO late_charge_assessments (id, installment_id, schedule_id, loan_offer_id, kind, "
                "charge_date, basis_amount, amount) SELECT gen_random_uuid(), installment_id, schedule_id, "
                "loan_offer_id, kind, charge_date, basis_amount, amount FROM late_charge_assessments LIMIT 1"
            )
        )
    await db_session.rollback()
    assert (await inst(db_session, r.schedule_id)).fee_due == one.fee_due


async def test_missed_days_are_caught_up_in_one_run(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    res = await assess(db_session, r.schedule_id, r.due1 + timedelta(days=30))
    assert res.charges == 30
    assert D("110") < res.total < D("112")  # ~KreditBee's 110.98 for 30 days


async def test_charges_stop_after_the_last_penal_day(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    res = await assess(db_session, r.schedule_id, r.due1 + timedelta(days=400))
    assert res.charges == 540  # 180 days on each of the three installments, never more
    assert await count(db_session, LateChargeAssessment, LateChargeAssessment.installment_id == (await inst(db_session, r.schedule_id)).id) == 180


async def test_the_total_never_exceeds_the_cap_of_what_was_due(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch, late_total_cap_percent_of_due="5")
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=400))
    one = await inst(db_session, r.schedule_id)
    assert one.fee_due == D("88.38")  # 5% x (1,617.65 + 150.00)


async def test_a_loan_whose_offer_did_not_enable_late_charges_is_never_charged(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch, late=False)
    assert (await assess(db_session, r.schedule_id, r.due1 + timedelta(days=90))).charges == 0
    assert (await inst(db_session, r.schedule_id)).fee_due == 0


async def test_a_later_pricing_change_does_not_change_an_existing_loans_late_terms(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch, late=False)
    await approved_pricing(monkeypatch, db_session, late_charges_enabled=True)  # newer version turns it on
    assert (await assess(db_session, r.schedule_id, r.due1 + timedelta(days=5))).charges == 0


async def test_unpriced_loans_are_never_charged(world, db_session, monkeypatch):
    r = await disbursed(world, db_session, monkeypatch)
    created = client.post(schedule_url(), json={"loan_offer_id": r.offer_id, "installment_count": 1}, headers=r.finance_headers)
    sid = created.json()["id"]
    client.post(schedule_url(f"/{sid}/activate"), headers=r.finance_headers)
    due = (await inst(db_session, sid)).due_date
    assert (await assess(db_session, sid, due + timedelta(days=40))).charges == 0


async def test_paying_the_overdue_principal_stops_further_charges(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=3))
    fee_before = (await inst(db_session, r.schedule_id)).fee_due
    # customer clears installment 1 in full: charges (fees) first, then interest, then principal
    owed = D("1767.65") + fee_before
    pid, ref = await started(world, r, str(owed), db_session)
    assert settle(ref, "SUCCESS", amount=str(owed)) == "SUCCESS"
    one = await inst(db_session, r.schedule_id)
    assert one.status == "PAID" and one.fee_paid == fee_before
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=60))  # installment 2 is now late
    assert (await inst(db_session, r.schedule_id)).fee_due == fee_before  # installment 1 is not charged again
    assert await count(db_session, LateChargeAssessment, LateChargeAssessment.installment_id == one.id) == 3
    p = await row(db_session, pid)
    assert (p.fee_applied, p.interest_applied, p.principal_applied) == (fee_before, D("150.00"), D("1617.65"))
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.PENAL_INCOME].balance == fee_before  # charges are their own income line
    assert balances[L.FEE_INCOME].balance == D("300.00")  # the processing fee is untouched


async def test_a_partial_payment_clears_charges_first_and_charges_continue_on_what_is_left(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=2))  # 64.71 + 1.60
    pid, ref = await started(world, r, "100.00", db_session)
    settle(ref, "SUCCESS", amount="100.00")
    one = await inst(db_session, r.schedule_id)
    assert one.fee_paid == D("66.31") and one.interest_paid == D("33.69") and one.principal_paid == 0
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=3))
    third = (await db_session.execute(select(LateChargeAssessment).order_by(LateChargeAssessment.charge_date.desc()))).scalars().first()
    assert third.basis_amount == D("1617.65")  # principal untouched, so still the full basis


async def test_a_reversed_payment_leaves_the_assessed_charges_in_place(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=2))
    pid, ref = await started(world, r, "100.00", db_session)
    settle(ref, "SUCCESS", amount="100.00")
    assert settle(ref, "REVERSED", amount="100.00") == "REVERSED"
    one = await inst(db_session, r.schedule_id)
    assert one.fee_due == D("66.31") and one.fee_paid == 0 and one.status == "SCHEDULED"
    balances = {b.code: b for b in await build_ledger_service(db_session).balances()}
    assert balances[L.PENAL_INCOME].balance == 0


async def test_schedule_totals_show_the_charges_to_the_customer(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    before = my_schedule(world, r).json()
    assert before["fee_total"] == "0.00" and before["total_payable"] == "5302.96"
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=1))
    after = my_schedule(world, r).json()
    assert after["fee_total"] == "64.71" and after["total_payable"] == "5367.67"
    assert after["total_remaining"] == "5367.67"
    assert after["installments"][0]["fee_due"] == "64.71"


async def test_the_database_only_lets_a_fee_grow_and_keeps_history_append_only(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    await assess(db_session, r.schedule_id, r.due1 + timedelta(days=2))
    for sql in (
        "UPDATE repayment_installments SET fee_due = fee_due - 1 WHERE fee_due > 0",
        "UPDATE repayment_installments SET principal_due = principal_due + 1",
        "UPDATE repayment_installments SET interest_due = interest_due + 1",
        "UPDATE late_charge_assessments SET amount = 1",
        "DELETE FROM late_charge_assessments",
    ):
        with pytest.raises(DBAPIError):
            await db_session.execute(text(sql))
        await db_session.rollback()


async def test_the_worker_assesses_overdue_charges(world, db_session, monkeypatch):
    r = await charged_loan(world, db_session, monkeypatch)
    later = r.due1 + timedelta(days=4)
    monkeypatch.setattr(late_service, "today_ist", lambda *a, **k: later)
    stats = await run_repayments()
    assert stats["late_charged"] == 4 and stats["errors"] == 0
    again = await run_repayments()  # a second pass is harmless
    assert again["late_charged"] == 0
    assert (await inst(db_session, r.schedule_id)).fee_due > D("64.71")
    # nothing else was disturbed: the books still match the schedule
    admin = client.get(schedule_url(f"/{r.schedule_id}"), headers=r.finance_headers).json()
    assert admin["ledger_matches_schedule"] is True
