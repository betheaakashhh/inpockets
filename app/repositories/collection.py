from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_user import AdminUser
from app.models.collection import CollectionCase, CollectionEvent
from app.models.repayment import RepaymentInstallment, RepaymentSchedule


class CollectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # -------------------------------------------------------------- planning

    async def overdue_schedule_ids(self, *, today: date, limit: int) -> list[uuid.UUID]:
        """ACTIVE schedules with an installment past due and principal or
        interest still unpaid (late charges alone do not count)."""
        outstanding = (
            RepaymentInstallment.principal_due
            - RepaymentInstallment.principal_paid
            + RepaymentInstallment.interest_due
            - RepaymentInstallment.interest_paid
        )
        rows = await self.session.execute(
            select(RepaymentSchedule.id)
            .join(RepaymentInstallment, RepaymentInstallment.schedule_id == RepaymentSchedule.id)
            .where(
                RepaymentSchedule.status == "ACTIVE",
                RepaymentInstallment.due_date < today,
                outstanding > 0,
            )
            .group_by(RepaymentSchedule.id)
            .order_by(func.min(RepaymentInstallment.due_date), RepaymentSchedule.id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def live_case_schedule_ids(self, *, limit: int) -> list[uuid.UUID]:
        rows = await self.session.execute(
            select(CollectionCase.schedule_id)
            .where(CollectionCase.status != "CLOSED")
            .order_by(CollectionCase.updated_at, CollectionCase.id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def reminder_case_ids(self, *, limit: int) -> list[uuid.UUID]:
        rows = await self.session.execute(
            select(CollectionCase.id)
            .where(CollectionCase.status != "CLOSED", CollectionCase.dpd >= 1)
            .order_by(CollectionCase.last_reminder_at.asc().nulls_first(), CollectionCase.id)
            .limit(limit)
        )
        return list(rows.scalars())

    async def escalation_case_ids(self, *, min_dpd: int, max_level: int, limit: int):
        rows = await self.session.execute(
            select(CollectionCase.id)
            .where(
                CollectionCase.status != "CLOSED",
                CollectionCase.dpd >= min_dpd,
                CollectionCase.escalation_level < max_level,
            )
            .order_by(CollectionCase.dpd.desc(), CollectionCase.id)
            .limit(limit)
        )
        return list(rows.scalars())

    # ----------------------------------------------------------------- cases

    async def get_case(self, case_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(CollectionCase).where(CollectionCase.id == case_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_live_case(self, schedule_id: uuid.UUID, *, for_update: bool = False):
        stmt = select(CollectionCase).where(
            CollectionCase.schedule_id == schedule_id, CollectionCase.status != "CLOSED"
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_case(self, **fields) -> uuid.UUID | None:
        """None when a live case for the schedule already exists (a race)."""
        result = await self.session.execute(
            insert(CollectionCase)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(
                index_elements=["schedule_id"], index_where=text("status <> 'CLOSED'")
            )
            .returning(CollectionCase.id)
        )
        return result.scalar_one_or_none()

    async def list_cases(
        self, *, status, bucket, assignee_admin_id, unassigned, min_dpd, limit: int
    ):
        stmt = select(CollectionCase)
        if status:
            stmt = stmt.where(CollectionCase.status == status)
        if bucket:
            stmt = stmt.where(CollectionCase.dpd_bucket == bucket)
        if assignee_admin_id:
            stmt = stmt.where(CollectionCase.assigned_to_admin_user_id == assignee_admin_id)
        if unassigned:
            stmt = stmt.where(CollectionCase.assigned_to_admin_user_id.is_(None))
        if min_dpd:
            stmt = stmt.where(CollectionCase.dpd >= min_dpd)
        rows = await self.session.execute(
            stmt.order_by(CollectionCase.dpd.desc(), CollectionCase.id).limit(limit)
        )
        return list(rows.scalars())

    async def summary(self):
        rows = await self.session.execute(
            select(
                CollectionCase.status,
                CollectionCase.dpd_bucket,
                func.count(),
                func.coalesce(
                    func.sum(
                        CollectionCase.overdue_principal
                        + CollectionCase.overdue_interest
                        + CollectionCase.overdue_fees
                    ),
                    0,
                ),
            )
            .where(CollectionCase.status != "CLOSED")
            .group_by(CollectionCase.status, CollectionCase.dpd_bucket)
            .order_by(CollectionCase.dpd_bucket, CollectionCase.status)
        )
        return [tuple(r) for r in rows.all()]

    # ---------------------------------------------------------------- events

    async def add_event(self, **fields) -> bool:
        """False when the same dedupe key already exists for the case."""
        result = await self.session.execute(
            insert(CollectionEvent)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing()
            .returning(CollectionEvent.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_events(self, case_id: uuid.UUID, *, limit: int = 500):
        rows = await self.session.execute(
            select(CollectionEvent)
            .where(CollectionEvent.case_id == case_id)
            .order_by(CollectionEvent.created_at, CollectionEvent.id)
            .limit(limit)
        )
        return list(rows.scalars())

    # ----------------------------------------------------------------- admin

    async def get_admin(self, admin_id: uuid.UUID):
        return (
            await self.session.execute(select(AdminUser).where(AdminUser.id == admin_id))
        ).scalar_one_or_none()
