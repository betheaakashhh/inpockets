"""Financial-reporting assertions against persisted PostgreSQL ledger records."""
# ruff: noqa: F811

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.domain import ledger as ledger_dom
from app.domain.ledger import TxKind
from app.models.reconciliation import ReconciliationRecord, ReconciliationRun
from app.models.repayment import RepaymentPayment
from app.repositories.reporting import ReportingRepository
from app.services.ledger_factory import build_ledger_service
from tests.api.test_disbursement_api import (  # noqa: F401
    Dev,
    env,
    ready,
)
from tests.api.test_disbursement_api import (
    create as create_disbursement,
)
from tests.api.test_disbursement_api import (
    current as current_disbursement,
)
from tests.api.test_disbursement_api import (
    hook as disbursement_hook,
)
from tests.api.test_disbursement_api import (
    post_hook as post_disbursement_hook,
)
from tests.api.test_disbursement_api import (
    run_once as run_disbursements,
)
from tests.api.test_loan_offer_api import world  # noqa: F401
from tests.api.test_repayment_api import active_loan, pay, settle
from tests.api.test_repayment_api import env as repayment_env  # noqa: F401


async def _payment_for_response(db_session, response):
    payment_id = response.json()["id"]
    return (
        await db_session.execute(
            select(RepaymentPayment).where(RepaymentPayment.id == payment_id)
        )
    ).scalar_one()


async def test_exposure_is_ledger_based_and_adjustments_are_not_repayments(
    world, db_session, monkeypatch
):
    loan = await active_loan(world, db_session, monkeypatch, count=1)
    paid = pay(world, loan, "1000.00")
    assert paid.status_code == 201, paid.text
    payment = await _payment_for_response(db_session, paid)
    assert settle(payment.provider_ref, "SUCCESS", amount="1000.00") == "SUCCESS"

    # Adjustments have no workflow endpoint, but the append-only ledger does
    # support them.  The report must surface their principal effect separately.
    await build_ledger_service(db_session).post(
        kind=TxKind.ADJUSTMENT,
        idempotency_key=f"reporting-test-adjustment:{uuid4()}",
        source_type="reporting_test",
        source_id=uuid4(),
        loan_offer_id=payment.loan_offer_id,
        user_id=payment.user_id,
        lines=[
            ledger_dom.debit(ledger_dom.LOAN_PRINCIPAL, Decimal("20.00")),
            ledger_dom.credit(ledger_dom.BANK, Decimal("20.00")),
        ],
        description="Reporting integration-test adjustment",
    )

    row = (
        await ReportingRepository(db_session).exposure(
            start_at=None, end_at=None, limit=10, offset=0
        )
    )[0]
    assert row["net_disbursed_principal"] == "5000.00"
    assert row["net_repayment_principal_reduction"] == "1000.00"
    assert row["adjustment_principal_effect"] == "20.00"
    assert row["outstanding_principal"] == "4020.00"
    assert row["principal_paid"] == "1000.00"
    assert row["schedule_to_ledger_variance"] == "0.00"
    assert row["accounting_formula_variance"] == "0.00"


async def test_repayment_report_keeps_operational_events_separate_from_net_ledger_cash(
    world, db_session, monkeypatch
):
    loan = await active_loan(world, db_session, monkeypatch, count=1)

    reversed_response = pay(world, loan, "1000.00")
    reversed_payment = await _payment_for_response(db_session, reversed_response)
    assert settle(reversed_payment.provider_ref, "SUCCESS", amount="1000.00") == "SUCCESS"
    assert settle(reversed_payment.provider_ref, "REVERSED", amount="1000.00") == "REVERSED"

    successful_response = pay(world, loan, "500.00")
    successful_payment = await _payment_for_response(db_session, successful_response)
    assert settle(successful_payment.provider_ref, "SUCCESS", amount="500.00") == "SUCCESS"

    failed_response = pay(world, loan, "200.00")
    failed_payment = await _payment_for_response(db_session, failed_response)
    assert settle(failed_payment.provider_ref, "FAILED", amount="200.00") == "FAILED"

    rows = await ReportingRepository(db_session).repayments(
        start_at=None, end_at=None, limit=10, offset=0
    )
    by_status = {row["status"]: row for row in rows}

    assert by_status["REVERSED"] | {
        "attempted_amount": "1000.00",
        "gross_successful_amount": "1000.00",
        "retained_net_amount": "0.00",
        "net_principal_applied": "0.00",
    } == by_status["REVERSED"]
    assert by_status["SUCCESS"] | {
        "attempted_amount": "500.00",
        "gross_successful_amount": "500.00",
        "retained_net_amount": "500.00",
        "net_principal_applied": "500.00",
    } == by_status["SUCCESS"]
    assert by_status["FAILED"] | {
        "attempted_amount": "200.00",
        "gross_successful_amount": "0",
        "retained_net_amount": "0",
    } == by_status["FAILED"]


async def test_disbursement_report_excludes_reversed_payout_from_net_cash(
    world, db_session, monkeypatch
):
    loan = await ready(world, db_session, monkeypatch)
    Dev.behaviour = "instant"
    assert create_disbursement(loan.finance_headers, loan.offer_id).status_code == 201
    await run_disbursements()
    disbursement = await current_disbursement(db_session, loan.offer_id)

    body, headers = disbursement_hook(
        disbursement.provider_ref, "REVERSED", amount=str(disbursement.amount)
    )
    assert post_disbursement_hook(body, headers).json()["outcome"] == "REVERSED"

    row = (
        await ReportingRepository(db_session).disbursements(
            start_at=None, end_at=None, limit=10, offset=0
        )
    )[0]
    assert row["status"] == "REVERSED"
    assert row["attempted_amount"] == "5000.00"
    assert row["gross_successful_amount"] == "5000.00"
    assert row["reversed_amount"] == "5000.00"
    assert row["net_disbursed_amount"] == "0.00"


async def test_disbursement_report_does_not_book_failed_attempts(
    world, db_session, monkeypatch
):
    loan = await ready(world, db_session, monkeypatch)
    Dev.behaviour = "reject"
    assert create_disbursement(loan.finance_headers, loan.offer_id).status_code == 201
    await run_disbursements()

    row = (
        await ReportingRepository(db_session).disbursements(
            start_at=None, end_at=None, limit=10, offset=0
        )
    )[0]
    assert row["status"] == "FAILED"
    assert row["attempted_amount"] == "5000.00"
    assert row["failed_amount"] == "5000.00"
    assert row["gross_successful_amount"] == "0"
    assert row["net_disbursed_amount"] == "0"


async def test_reconciliation_report_keeps_missing_amounts_distinct_from_zero(db_session):
    run = ReconciliationRun(
        flow="COLLECTION",
        provider="development",
        report_date=datetime.now(UTC).date(),
        status="RUNNING",
    )
    db_session.add(run)
    await db_session.flush()
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ReconciliationRecord(
                run_id=run.id,
                flow="COLLECTION",
                provider="development",
                provider_ref="missing-external",
                status="UNMATCHED",
                discrepancy="MISSING_EXTERNAL",
                detail="Internal settlement is absent from the provider report.",
                internal_amount=Decimal("100.00"),
                ledger_net=Decimal("100.00"),
                expected_ledger_net=Decimal("100.00"),
                external_count=0,
                review_status="OPEN",
                created_at=now,
            ),
            ReconciliationRecord(
                run_id=run.id,
                flow="COLLECTION",
                provider="development",
                provider_ref="amount-mismatch",
                status="MISMATCH",
                discrepancy="AMOUNT_MISMATCH",
                detail="The provider amount differs from the internal amount.",
                internal_amount=Decimal("100.00"),
                external_amount=Decimal("80.00"),
                ledger_net=Decimal("100.00"),
                expected_ledger_net=Decimal("100.00"),
                external_count=1,
                review_status="OPEN",
                created_at=now,
            ),
            ReconciliationRecord(
                run_id=run.id,
                flow="COLLECTION",
                provider="development",
                provider_ref="ledger-mismatch",
                status="REQUIRES_REVIEW",
                discrepancy="LEDGER_MISMATCH",
                detail="The ledger bank movement differs from the expected movement.",
                internal_amount=Decimal("50.00"),
                external_amount=Decimal("50.00"),
                ledger_net=Decimal("10.00"),
                expected_ledger_net=Decimal("50.00"),
                external_count=1,
                review_status="OPEN",
                created_at=now,
            ),
            ReconciliationRecord(
                run_id=run.id,
                flow="COLLECTION",
                provider="development",
                provider_ref="matched",
                status="MATCHED",
                discrepancy=None,
                detail="Matched.",
                internal_amount=Decimal("10.00"),
                external_amount=Decimal("10.00"),
                ledger_net=Decimal("10.00"),
                expected_ledger_net=Decimal("10.00"),
                external_count=1,
                review_status="NOT_REQUIRED",
                created_at=now,
            ),
        ]
    )
    await db_session.flush()

    rows = await ReportingRepository(db_session).reconciliation(
        start_at=None, end_at=None, limit=10, offset=0
    )
    by_status = {row["status"]: row for row in rows}

    assert set(by_status) == {"UNMATCHED", "MISMATCH", "REQUIRES_REVIEW"}
    assert by_status["UNMATCHED"]["external_amount_total"] is None
    assert by_status["UNMATCHED"]["amount_comparison_count"] == 0
    assert by_status["MISMATCH"]["external_minus_internal_total"] == "-20.00"
    assert by_status["REQUIRES_REVIEW"]["ledger_minus_expected_total"] == "-40.00"
