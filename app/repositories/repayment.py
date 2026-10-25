from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repayment import OPEN_STATUSES
from app.models.repayment import (
    RepaymentAllocation,
    RepaymentEvent,
    RepaymentInstallment,
    RepaymentPayment,
    RepaymentSchedule,
)


class RepaymentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ----------------------------------------------------------- schedules

    async def create_schedule(self, **fields) -> RepaymentSchedule:
        row = RepaymentSchedule(**fields)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def add_installments(self, rows: list[dict]) -> list[RepaymentInstallment]:
        objs = [RepaymentInstallment(**r) for r in rows]
        self.session.add_all(objs)
        await self.session.flush()
        return objs

    async def get_schedule(self, schedule_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(RepaymentSchedule).where(RepaymentSchedule.id == schedule_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_live_schedule_for_offer(self, offer_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(RepaymentSchedule).where(
            RepaymentSchedule.loan_offer_id == offer_id,
            RepaymentSchedule.status.in_(["DRAFT", "ACTIVE"]),
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_active_schedule_for_offer(self, offer_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(RepaymentSchedule).where(
            RepaymentSchedule.loan_offer_id == offer_id, RepaymentSchedule.status == "ACTIVE"
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_installments(self, schedule_id: uuid.UUID, *, for_update: bool = False):
        stmt = (
            select(RepaymentInstallment)
            .where(RepaymentInstallment.schedule_id == schedule_id)
            .order_by(RepaymentInstallment.installment_number)
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return list((await self.session.execute(stmt)).scalars())

    async def list_schedules(self, *, loan_offer_id, limit: int):
        stmt = select(RepaymentSchedule)
        if loan_offer_id:
            stmt = stmt.where(RepaymentSchedule.loan_offer_id == loan_offer_id)
        rows = await self.session.execute(stmt.order_by(RepaymentSchedule.created_at.desc()).limit(limit))
        return list(rows.scalars())

    # ------------------------------------------------------------ payments

    async def create_payment(self, **fields) -> RepaymentPayment:
        row = RepaymentPayment(**fields)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_payment(self, payment_id: uuid.UUID, *, for_update: bool = False,
                          skip_locked: bool = False):
        stmt = select(RepaymentPayment).where(RepaymentPayment.id == payment_id)
        if for_update:
            stmt = stmt.with_for_update(skip_locked=skip_locked).execution_options(
                populate_existing=True
            )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_payment_by_client_key(self, user_id: uuid.UUID, key: str):
        return (
            await self.session.execute(
                select(RepaymentPayment).where(
                    RepaymentPayment.user_id == user_id,
                    RepaymentPayment.client_idempotency_key == key,
                )
            )
        ).scalar_one_or_none()

    async def get_payment_by_provider_ref(self, *, provider: str, provider_ref: str):
        return (
            await self.session.execute(
                select(RepaymentPayment).where(
                    RepaymentPayment.provider == provider,
                    RepaymentPayment.provider_ref == provider_ref,
                )
            )
        ).scalar_one_or_none()

    async def get_payment_by_idempotency_key(self, key: str):
        return (
            await self.session.execute(
                select(RepaymentPayment).where(RepaymentPayment.idempotency_key == key)
            )
        ).scalar_one_or_none()

    async def count_open_payments(self, schedule_id: uuid.UUID) -> int:
        return (
            await self.session.execute(
                select(func.count())
                .select_from(RepaymentPayment)
                .where(
                    RepaymentPayment.schedule_id == schedule_id,
                    RepaymentPayment.status.in_([s.value for s in OPEN_STATUSES]),
                )
            )
        ).scalar_one()

    async def list_payments_for_offer(self, offer_id: uuid.UUID, *, user_id=None, limit=100):
        stmt = select(RepaymentPayment).where(RepaymentPayment.loan_offer_id == offer_id)
        if user_id:
            stmt = stmt.where(RepaymentPayment.user_id == user_id)
        rows = await self.session.execute(
            stmt.order_by(RepaymentPayment.requested_at.desc()).limit(limit)
        )
        return list(rows.scalars())

    async def list_payments_filtered(self, *, status, loan_offer_id, limit: int):
        stmt = select(RepaymentPayment)
        if status:
            stmt = stmt.where(RepaymentPayment.status == status)
        if loan_offer_id:
            stmt = stmt.where(RepaymentPayment.loan_offer_id == loan_offer_id)
        rows = await self.session.execute(
            stmt.order_by(RepaymentPayment.requested_at.desc()).limit(limit)
        )
        return list(rows.scalars())

    async def list_undispatched_ids(self, *, requested_before: datetime, limit: int):
        """INITIATED rows the provider may never have received (crash/timeout)."""
        rows = await self.session.execute(
            select(RepaymentPayment.id)
            .where(
                RepaymentPayment.status == "INITIATED",
                RepaymentPayment.requested_at <= requested_before,
            )
            .order_by(RepaymentPayment.requested_at)
            .limit(limit)
        )
        return [r[0] for r in rows]

    async def list_reconcile_candidate_ids(
        self, *, requested_before: datetime, polled_before: datetime, limit: int
    ):
        rows = await self.session.execute(
            select(RepaymentPayment.id)
            .where(
                RepaymentPayment.status == "PENDING",
                RepaymentPayment.requested_at <= requested_before,
                (RepaymentPayment.last_polled_at.is_(None))
                | (RepaymentPayment.last_polled_at <= polled_before),
            )
            .order_by(RepaymentPayment.requested_at)
            .limit(limit)
        )
        return [r[0] for r in rows]

    # --------------------------------------------------------- allocations

    async def add_allocations(self, rows: list[dict]) -> None:
        self.session.add_all([RepaymentAllocation(**r) for r in rows])
        await self.session.flush()

    async def list_allocations(self, payment_id: uuid.UUID) -> list[RepaymentAllocation]:
        rows = await self.session.execute(
            select(RepaymentAllocation).where(RepaymentAllocation.payment_id == payment_id)
        )
        return list(rows.scalars())

    # -------------------------------------------------------------- events

    async def insert_event(self, **fields) -> uuid.UUID | None:
        result = await self.session.execute(
            insert(RepaymentEvent)
            .values(**fields)
            .on_conflict_do_nothing(constraint="uq_repayment_event_provider_event")
            .returning(RepaymentEvent.id)
        )
        return result.scalar_one_or_none()

    async def set_event_outcome(self, event_id: uuid.UUID, outcome: str) -> None:
        event = await self.session.get(RepaymentEvent, event_id)
        event.outcome = outcome
        await self.session.flush()

    async def list_events(self, payment_id: uuid.UUID) -> list[RepaymentEvent]:
        rows = await self.session.execute(
            select(RepaymentEvent)
            .where(RepaymentEvent.payment_id == payment_id)
            .order_by(RepaymentEvent.received_at)
        )
        return list(rows.scalars())
