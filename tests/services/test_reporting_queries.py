from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories.reporting import ReportingRepository

pytestmark = pytest.mark.unit


def _sql(statement) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


@pytest.mark.asyncio
async def test_exposure_query_uses_ledger_principal_balance():
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one=lambda: SimpleNamespace(principal_due=100)),
                SimpleNamespace(
                    one=lambda: SimpleNamespace(
                        interest_due=10,
                        fee_due=2,
                        installments=1,
                    )
                ),
                SimpleNamespace(
                    one=lambda: SimpleNamespace(
                        outstanding_principal=80,
                        adjustment_activity=5,
                        net_repayment_principal_reduction=25,
                        net_disbursed_principal=100,
                    )
                ),
            ]
        )
    )

    rows = await ReportingRepository(session).exposure(
        start_at=None,
        end_at=None,
        limit=10,
        offset=0,
    )

    assert rows[0]["outstanding_principal"] == "80"
    assert rows[0]["principal_paid"] == "25"
    assert rows[0]["schedule_to_ledger_variance"] == "0"
    assert rows[0]["accounting_formula_variance"] == "0"
    statements = [call.args[0] for call in session.execute.await_args_list]
    ledger_sql = _sql(statements[2])
    assert "ledger_transactions" in ledger_sql
    assert "ledger_entries" in ledger_sql
    assert "code_1" not in ledger_sql.lower()
    assert "ledger_accounts.code =" in ledger_sql.lower()
    assert "principal_paid" not in ledger_sql.lower()
    assert "exists" in ledger_sql.lower()


@pytest.mark.asyncio
async def test_repayment_report_separates_reversed_cash_from_retained_cash():
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=[
                SimpleNamespace(
                    status="REVERSED",
                    count=1,
                    attempted_amount=100,
                    gross_successful_amount=100,
                    retained_net_amount=0,
                    principal_applied=0,
                    interest_applied=0,
                    fee_applied=0,
                    unapplied_amount=0,
                )
            ]
        )
    )

    rows = await ReportingRepository(session).repayments(
        start_at=None,
        end_at=None,
        limit=10,
        offset=0,
    )

    assert rows == [
        {
            "status": "REVERSED",
            "count": 1,
            "attempted_amount": "100",
            "gross_successful_amount": "100",
            "retained_net_amount": "0",
            "confirmed_amount": "0",
                "principal_applied": "0",
                "interest_applied": "0",
            "fee_applied": "0",
            "unapplied_amount": "0",
                "net_principal_applied": "0",
                "net_interest_applied": "0",
                "net_fee_applied": "0",
                "net_unapplied_amount": "0",
                "financial_basis": "ledger_postings",
        }
    ]


@pytest.mark.asyncio
async def test_risk_fraud_pagination_is_applied_to_combined_sql_query():
    session = SimpleNamespace(execute=AsyncMock(return_value=[]))

    await ReportingRepository(session).risk_fraud(
        start_at=None,
        end_at=None,
        limit=7,
        offset=14,
    )

    statement = session.execute.await_args.args[0]
    sql = _sql(statement)
    assert "row_number()" in sql.lower()
    assert " OFFSET 14" in sql
    assert " LIMIT 8" in sql


@pytest.mark.asyncio
async def test_collection_period_queries_use_opened_and_closed_timestamps():
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one=lambda: SimpleNamespace(cases=2, principal=20)),
                SimpleNamespace(one=lambda: SimpleNamespace(cases=1, principal=10)),
            ]
        )
    )

    await ReportingRepository(session).collections(
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 2, 1, tzinfo=UTC),
        limit=10,
        offset=0,
    )

    opened_sql = _sql(session.execute.await_args_list[0].args[0])
    closed_sql = _sql(session.execute.await_args_list[1].args[0])
    assert "opened_at" in opened_sql
    assert "closed_at" in closed_sql
    assert "updated_at" not in opened_sql
    assert "updated_at" not in closed_sql
