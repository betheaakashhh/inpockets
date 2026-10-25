from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction


class LedgerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def accounts_by_code(self, codes) -> dict[str, LedgerAccount]:
        rows = await self.session.execute(
            select(LedgerAccount).where(LedgerAccount.code.in_(list(codes)))
        )
        return {a.code: a for a in rows.scalars()}

    async def list_accounts(self) -> list[LedgerAccount]:
        rows = await self.session.execute(select(LedgerAccount).order_by(LedgerAccount.code))
        return list(rows.scalars())

    async def get_by_key(self, key: str) -> LedgerTransaction | None:
        return (
            await self.session.execute(
                select(LedgerTransaction).where(LedgerTransaction.idempotency_key == key)
            )
        ).scalar_one_or_none()

    async def get_by_id(self, tx_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(LedgerTransaction).where(LedgerTransaction.id == tx_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_reversal_of(self, tx_id: uuid.UUID) -> LedgerTransaction | None:
        return (
            await self.session.execute(
                select(LedgerTransaction).where(LedgerTransaction.reverses_transaction_id == tx_id)
            )
        ).scalar_one_or_none()

    async def insert_header(self, **fields) -> uuid.UUID | None:
        """None when the idempotency key already exists (a concurrent or
        repeated posting): the caller then reads the existing row."""
        result = await self.session.execute(
            insert(LedgerTransaction)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(constraint="uq_ledger_tx_idempotency_key")
            .returning(LedgerTransaction.id)
        )
        return result.scalar_one_or_none()

    async def insert_entries(self, rows: list[dict]) -> None:
        await self.session.execute(
            insert(LedgerEntry), [{"id": uuid.uuid4(), **r} for r in rows]
        )

    async def entries_with_accounts(self, tx_id: uuid.UUID):
        rows = await self.session.execute(
            select(LedgerEntry, LedgerAccount.code)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerEntry.transaction_id == tx_id)
            .order_by(LedgerEntry.line_no)
        )
        return list(rows.all())

    async def list_transactions(
        self, *, loan_offer_id: uuid.UUID | None, limit: int
    ) -> list[LedgerTransaction]:
        stmt = select(LedgerTransaction)
        if loan_offer_id:
            stmt = stmt.where(LedgerTransaction.loan_offer_id == loan_offer_id)
        rows = await self.session.execute(
            stmt.order_by(LedgerTransaction.posted_at.desc(), LedgerTransaction.id).limit(limit)
        )
        return list(rows.scalars())

    async def totals_by_account(self, *, loan_offer_id: uuid.UUID | None = None):
        """(account, debit_total, credit_total) from entries: the only balance source."""
        debit_sum = func.coalesce(
            func.sum(case((LedgerEntry.direction == "DEBIT", LedgerEntry.amount), else_=0)), 0
        )
        credit_sum = func.coalesce(
            func.sum(case((LedgerEntry.direction == "CREDIT", LedgerEntry.amount), else_=0)), 0
        )
        stmt = (
            select(LedgerAccount, debit_sum, credit_sum)
            .select_from(LedgerAccount)
            .outerjoin(LedgerEntry, LedgerEntry.account_id == LedgerAccount.id)
        )
        if loan_offer_id:
            stmt = stmt.join(
                LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id
            ).where(LedgerTransaction.loan_offer_id == loan_offer_id)
        rows = await self.session.execute(stmt.group_by(LedgerAccount.id).order_by(LedgerAccount.code))
        return [(a, Decimal(d), Decimal(c)) for a, d, c in rows.all()]
