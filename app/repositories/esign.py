from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.esign import LIVE_STATUSES
from app.models.esign_event import ESignEvent
from app.models.esign_transaction import ESignTransaction


class ESignRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> ESignTransaction:
        tx = ESignTransaction(**fields)
        self.session.add(tx)
        await self.session.flush()
        await self.session.refresh(tx)
        return tx

    async def get_by_id(self, tx_id: uuid.UUID) -> ESignTransaction | None:
        return (
            await self.session.execute(
                select(ESignTransaction).where(ESignTransaction.id == tx_id)
            )
        ).scalar_one_or_none()

    async def get_by_provider_ref_for_update(
        self, *, provider: str, provider_ref: str
    ) -> ESignTransaction | None:
        return (
            await self.session.execute(
                select(ESignTransaction)
                .where(
                    ESignTransaction.provider == provider,
                    ESignTransaction.provider_ref == provider_ref,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def get_live_for_offer(
        self, offer_id: uuid.UUID, *, for_update: bool = False
    ) -> ESignTransaction | None:
        stmt = select(ESignTransaction).where(
            ESignTransaction.loan_offer_id == offer_id,
            ESignTransaction.status.in_([s.value for s in LIVE_STATUSES]),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def latest_for_offer(self, offer_id: uuid.UUID) -> ESignTransaction | None:
        return (
            await self.session.execute(
                select(ESignTransaction)
                .where(ESignTransaction.loan_offer_id == offer_id)
                .order_by(ESignTransaction.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def list_due(
        self, *, statuses: list[str], limit: int
    ) -> list[ESignTransaction]:
        rows = await self.session.execute(
            select(ESignTransaction)
            .where(ESignTransaction.status.in_(statuses))
            .order_by(ESignTransaction.initiated_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows.scalars())

    async def insert_event(self, **fields) -> uuid.UUID | None:
        """Insert once per (provider, provider_event_id); None if duplicate."""
        result = await self.session.execute(
            insert(ESignEvent)
            .values(**fields)
            .on_conflict_do_nothing(constraint="uq_esign_event_provider_event")
            .returning(ESignEvent.id)
        )
        return result.scalar_one_or_none()

    async def update_event(self, event_id: uuid.UUID, **fields) -> None:
        event = await self.session.get(ESignEvent, event_id)
        for key, value in fields.items():
            setattr(event, key, value)
        await self.session.flush()

    async def list_events(self, tx_id: uuid.UUID) -> list[ESignEvent]:
        rows = await self.session.execute(
            select(ESignEvent)
            .where(ESignEvent.esign_transaction_id == tx_id)
            .order_by(ESignEvent.received_at)
        )
        return list(rows.scalars())

    async def count_for_offer(self, offer_id: uuid.UUID) -> int:
        from sqlalchemy import func

        return (
            await self.session.execute(
                select(func.count())
                .select_from(ESignTransaction)
                .where(ESignTransaction.loan_offer_id == offer_id)
            )
        ).scalar_one()
