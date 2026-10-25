from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.late_charge import LateChargeAssessment
from app.models.repayment import RepaymentInstallment, RepaymentSchedule


class LateChargeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def schedules_with_overdue(self, *, today: date, limit: int) -> list[uuid.UUID]:
        """ACTIVE schedules with at least one unpaid installment past its due date."""
        stmt = (
            select(RepaymentSchedule.id)
            .join(RepaymentInstallment, RepaymentInstallment.schedule_id == RepaymentSchedule.id)
            .where(
                RepaymentSchedule.status == "ACTIVE",
                RepaymentInstallment.due_date < today,
                RepaymentInstallment.status != "PAID",
            )
            .group_by(RepaymentSchedule.id)
            .order_by(func.min(RepaymentInstallment.due_date))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def charged_so_far(self, installment_id: uuid.UUID) -> tuple[Decimal, date | None]:
        row = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(LateChargeAssessment.amount), 0),
                    func.max(LateChargeAssessment.charge_date),
                ).where(LateChargeAssessment.installment_id == installment_id)
            )
        ).one()
        return Decimal(row[0]), row[1]

    async def add(self, **fields) -> bool:
        """False when that installment/day was already charged (re-run)."""
        result = await self.session.execute(
            insert(LateChargeAssessment)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(constraint="uq_late_charge_installment_day")
            .returning(LateChargeAssessment.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_for_schedule(self, schedule_id: uuid.UUID) -> list[LateChargeAssessment]:
        rows = await self.session.execute(
            select(LateChargeAssessment)
            .where(LateChargeAssessment.schedule_id == schedule_id)
            .order_by(LateChargeAssessment.charge_date, LateChargeAssessment.kind)
        )
        return list(rows.scalars())
