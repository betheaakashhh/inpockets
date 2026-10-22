from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bank_verification import IN_FLIGHT
from app.models.bank_account_verification import BankAccountVerification as Row


class BankVerificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_user(self, user_id: uuid.UUID) -> None:
        """Serialise verification requests for one user (transaction scoped)."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"bank-verification:{user_id}"},
        )

    async def create(self, **fields) -> Row:
        row = Row(**fields)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_by_id(self, row_id: uuid.UUID, *, for_update: bool = False) -> Row | None:
        stmt = select(Row).where(Row.id == row_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_in_flight(self, user_id: uuid.UUID) -> Row | None:
        return (
            await self.session.execute(
                select(Row)
                .where(Row.user_id == user_id, Row.status.in_([s.value for s in IN_FLIGHT]))
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def get_current_verified(
        self, user_id: uuid.UUID, *, for_update: bool = False
    ) -> Row | None:
        stmt = select(Row).where(
            Row.user_id == user_id,
            Row.status == "VERIFIED",
            Row.superseded_at.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def latest_for_user(self, user_id: uuid.UUID) -> Row | None:
        return (
            await self.session.execute(
                select(Row)
                .where(Row.user_id == user_id)
                .order_by(Row.requested_at.desc(), Row.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Row]:
        rows = await self.session.execute(
            select(Row).where(Row.user_id == user_id).order_by(Row.requested_at.desc())
        )
        return list(rows.scalars())

    async def count_since(self, user_id: uuid.UUID, since: datetime) -> int:
        return (
            await self.session.execute(
                select(func.count())
                .select_from(Row)
                .where(Row.user_id == user_id, Row.requested_at >= since)
            )
        ).scalar_one()

    async def verified_for_other_user(
        self, *, fingerprint: str, user_id: uuid.UUID
    ) -> bool:
        found = await self.session.execute(
            select(Row.id)
            .where(
                Row.account_fingerprint == fingerprint,
                Row.user_id != user_id,
                Row.status == "VERIFIED",
                Row.superseded_at.is_(None),
            )
            .limit(1)
        )
        return found.first() is not None

    async def list_due(self, *, statuses: list[str], limit: int) -> list[Row]:
        rows = await self.session.execute(
            select(Row)
            .where(Row.status.in_(statuses))
            .order_by(Row.requested_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows.scalars())

    async def list_needing_rotation(self, *, active_key_id: str, limit: int) -> list[Row]:
        rows = await self.session.execute(
            select(Row)
            .where(Row.encryption_key_id != active_key_id)
            .order_by(Row.requested_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows.scalars())
