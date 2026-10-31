from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import ledger as ledger_dom
from app.domain.reconciliation import Flow, InternalItem
from app.models.disbursement import Disbursement
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction
from app.models.reconciliation import ReconciliationRecord, ReconciliationRun
from app.models.repayment import RepaymentPayment

FINAL = ("SUCCESS", "REVERSED", "FAILED")

# flow -> (model, ledger source_type)
_SOURCES = {
    Flow.COLLECTION: (RepaymentPayment, "repayment_payment"),
    Flow.DISBURSEMENT: (Disbursement, "disbursement"),
}


class ReconciliationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------------------------------------------------------------- runs

    async def get_run(self, run_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(ReconciliationRun).where(ReconciliationRun.id == run_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_run_for_day(self, flow: str, provider: str, report_date: date, *, for_update=False):
        stmt = select(ReconciliationRun).where(
            ReconciliationRun.flow == flow,
            ReconciliationRun.provider == provider,
            ReconciliationRun.report_date == report_date,
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_run(self, **fields) -> bool:
        """False when that flow/provider/day already has a run (a concurrent claim)."""
        result = await self.session.execute(
            insert(ReconciliationRun)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(constraint="uq_recon_run_day")
            .returning(ReconciliationRun.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_runs(self, *, flow: str | None, status: str | None, limit: int):
        stmt = select(ReconciliationRun)
        if flow:
            stmt = stmt.where(ReconciliationRun.flow == flow)
        if status:
            stmt = stmt.where(ReconciliationRun.status == status)
        rows = await self.session.execute(
            stmt.order_by(ReconciliationRun.report_date.desc(), ReconciliationRun.flow).limit(limit)
        )
        return list(rows.scalars())

    async def days_needing_work(
        self, *, flow: str, provider: str, days: list[date], max_attempts: int
    ) -> list[date]:
        """Days in `days` with no run, a FAILED run still under the attempt
        limit, or a RUNNING run (the service decides whether it is stale)."""
        rows = await self.session.execute(
            select(ReconciliationRun.report_date, ReconciliationRun.status, ReconciliationRun.attempts)
            .where(
                ReconciliationRun.flow == flow,
                ReconciliationRun.provider == provider,
                ReconciliationRun.report_date.in_(days),
            )
        )
        known = {d: (s, a) for d, s, a in rows.all()}
        out = []
        for day in days:
            state = known.get(day)
            if state is None or state[0] == "RUNNING" or (
                state[0] == "FAILED" and state[1] < max_attempts
            ):
                out.append(day)
        return out

    # -------------------------------------------------------- our own side

    def _date_expr(self, model):
        return func.coalesce(model.reversed_at, model.completed_at)

    async def items_in_window(
        self, flow: Flow, *, provider: str, start: datetime, end: datetime, limit: int
    ) -> list:
        model, _ = _SOURCES[flow]
        day = self._date_expr(model)
        rows = await self.session.execute(
            select(model)
            .where(
                model.provider == provider,
                model.status.in_(("SUCCESS", "REVERSED")),
                day >= start,
                day < end,
            )
            .order_by(day, model.id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def items_by_refs(self, flow: Flow, *, provider: str, refs: list[str]) -> list:
        if not refs:
            return []
        model, _ = _SOURCES[flow]
        rows = await self.session.execute(
            select(model).where(model.provider == provider, model.provider_ref.in_(refs))
        )
        return list(rows.scalars())

    async def bank_net(self, flow: Flow, ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """Net movement (debits - credits) of the bank account per source item,
        reversals included. Items with no posting are absent."""
        if not ids:
            return {}
        _, source_type = _SOURCES[flow]
        signed = case(
            (LedgerEntry.direction == "DEBIT", LedgerEntry.amount), else_=-LedgerEntry.amount
        )
        rows = await self.session.execute(
            select(LedgerTransaction.source_id, func.sum(signed))
            .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(
                LedgerTransaction.source_type == source_type,
                LedgerTransaction.source_id.in_(ids),
                LedgerAccount.code == ledger_dom.BANK,
            )
            .group_by(LedgerTransaction.source_id)
        )
        return {sid: Decimal(total) for sid, total in rows.all()}

    def to_internal(self, flow: Flow, row, net: dict[uuid.UUID, Decimal]) -> InternalItem:
        return InternalItem(
            id=row.id,
            ref=row.provider_ref,
            amount=Decimal(row.amount),
            status=row.status,
            ledger_net=net.get(row.id, Decimal("0.00")),
        )

    # ------------------------------------------------------------ records

    async def add_record(self, **fields) -> bool:
        result = await self.session.execute(
            insert(ReconciliationRecord)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(constraint="uq_recon_record_run_ref")
            .returning(ReconciliationRecord.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_record(self, record_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(ReconciliationRecord).where(ReconciliationRecord.id == record_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_records(
        self,
        *,
        run_id: uuid.UUID | None,
        flow: str | None,
        status: str | None,
        review_status: str | None,
        limit: int,
    ):
        stmt = select(ReconciliationRecord)
        if run_id:
            stmt = stmt.where(ReconciliationRecord.run_id == run_id)
        if flow:
            stmt = stmt.where(ReconciliationRecord.flow == flow)
        if status:
            stmt = stmt.where(ReconciliationRecord.status == status)
        if review_status:
            stmt = stmt.where(ReconciliationRecord.review_status == review_status)
        rows = await self.session.execute(
            stmt.order_by(ReconciliationRecord.created_at.desc(), ReconciliationRecord.id).limit(limit)
        )
        return list(rows.scalars())

    async def open_summary(self) -> list[tuple[str, str, str, int]]:
        rows = await self.session.execute(
            select(
                ReconciliationRecord.flow,
                ReconciliationRecord.status,
                ReconciliationRecord.review_status,
                func.count(),
            )
            .where(ReconciliationRecord.review_status.in_(("OPEN", "IN_REVIEW")))
            .group_by(
                ReconciliationRecord.flow,
                ReconciliationRecord.status,
                ReconciliationRecord.review_status,
            )
            .order_by(ReconciliationRecord.flow, ReconciliationRecord.status)
        )
        return [tuple(r) for r in rows.all()]
