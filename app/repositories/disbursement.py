from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.disbursement import LIVE_STATUSES
from app.models.disbursement import Disbursement, DisbursementEvent


class DisbursementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> Disbursement:
        row = Disbursement(**fields)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_by_id(self, row_id: uuid.UUID, *, for_update: bool = False,
                        skip_locked: bool = False) -> Disbursement | None:
        stmt = select(Disbursement).where(Disbursement.id == row_id)
        if for_update:
            stmt = stmt.with_for_update(skip_locked=skip_locked)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_provider_ref_for_update(
        self, *, provider: str, provider_ref: str
    ) -> Disbursement | None:
        return (
            await self.session.execute(
                select(Disbursement)
                .where(Disbursement.provider == provider, Disbursement.provider_ref == provider_ref)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def get_by_idempotency_key_for_update(self, key: str) -> Disbursement | None:
        return (
            await self.session.execute(
                select(Disbursement).where(Disbursement.idempotency_key == key).with_for_update()
            )
        ).scalar_one_or_none()

    async def get_live_for_offer(self, offer_id: uuid.UUID) -> Disbursement | None:
        return (
            await self.session.execute(
                select(Disbursement).where(
                    Disbursement.loan_offer_id == offer_id,
                    Disbursement.status.in_([s.value for s in LIVE_STATUSES]),
                )
            )
        ).scalar_one_or_none()

    async def latest_for_offer(self, offer_id: uuid.UUID) -> Disbursement | None:
        return (
            await self.session.execute(
                select(Disbursement)
                .where(Disbursement.loan_offer_id == offer_id)
                .order_by(Disbursement.attempt.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def count_for_offer(self, offer_id: uuid.UUID) -> int:
        return (
            await self.session.execute(
                select(func.count()).select_from(Disbursement).where(
                    Disbursement.loan_offer_id == offer_id
                )
            )
        ).scalar_one()

    async def list_pending_for_claim(self, *, limit: int) -> list[Disbursement]:
        rows = await self.session.execute(
            select(Disbursement)
            .where(Disbursement.status == "PENDING")
            .order_by(Disbursement.requested_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows.scalars())

    async def list_reconcile_candidate_ids(
        self, *, dispatched_before: datetime, polled_before: datetime, limit: int
    ) -> list[uuid.UUID]:
        rows = await self.session.execute(
            select(Disbursement.id)
            .where(
                Disbursement.status == "PROCESSING",
                Disbursement.dispatched_at <= dispatched_before,
                (Disbursement.last_polled_at.is_(None))
                | (Disbursement.last_polled_at <= polled_before),
            )
            .order_by(Disbursement.dispatched_at)
            .limit(limit)
        )
        return [r[0] for r in rows]

    async def list_filtered(
        self, *, status: str | None, loan_offer_id: uuid.UUID | None, limit: int
    ) -> list[Disbursement]:
        stmt = select(Disbursement)
        if status:
            stmt = stmt.where(Disbursement.status == status)
        if loan_offer_id:
            stmt = stmt.where(Disbursement.loan_offer_id == loan_offer_id)
        rows = await self.session.execute(
            stmt.order_by(Disbursement.requested_at.desc()).limit(limit)
        )
        return list(rows.scalars())

    async def insert_event(self, **fields) -> uuid.UUID | None:
        """Insert once per (provider, provider_event_id); None if duplicate."""
        result = await self.session.execute(
            insert(DisbursementEvent)
            .values(**fields)
            .on_conflict_do_nothing(constraint="uq_disbursement_event_provider_event")
            .returning(DisbursementEvent.id)
        )
        return result.scalar_one_or_none()

    async def set_event_outcome(self, event_id: uuid.UUID, outcome: str) -> None:
        event = await self.session.get(DisbursementEvent, event_id)
        event.outcome = outcome
        await self.session.flush()

    async def list_events(self, disbursement_id: uuid.UUID) -> list[DisbursementEvent]:
        rows = await self.session.execute(
            select(DisbursementEvent)
            .where(DisbursementEvent.disbursement_id == disbursement_id)
            .order_by(DisbursementEvent.received_at)
        )
        return list(rows.scalars())
