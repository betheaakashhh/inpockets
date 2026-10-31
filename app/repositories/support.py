from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.support import LIVE
from app.models.admin_user import AdminUser
from app.models.loan_application import LoanApplication
from app.models.loan_offer import LoanOffer
from app.models.support import SupportTicket, SupportTicketEvent
from app.models.user import User

_LIVE = [s.value for s in LIVE]


class SupportRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def next_sequence(self) -> int:
        return (await self.session.execute(select(func.nextval("support_ticket_number_seq")))).scalar_one()

    async def add_ticket(self, **fields) -> SupportTicket:
        row = SupportTicket(id=uuid.uuid4(), **fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, ticket_id, *, for_update: bool = False):
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_user(self, ticket_id, user_id, *, for_update: bool = False):
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_live(self, user_id) -> int:
        return (
            await self.session.execute(
                select(func.count()).select_from(SupportTicket).where(
                    SupportTicket.user_id == user_id, SupportTicket.status.in_(_LIVE)
                )
            )
        ).scalar_one()

    async def list_for_user(self, user_id, *, limit: int):
        rows = await self.session.execute(
            select(SupportTicket).where(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.created_at.desc(), SupportTicket.id).limit(limit)
        )
        return list(rows.scalars())

    async def list_admin(
        self, *, include_sensitive: bool, status, kind, category, assignee_admin_id, unassigned,
        overdue_before: datetime | None, limit: int,
    ):
        stmt = select(SupportTicket)
        if not include_sensitive:
            stmt = stmt.where(SupportTicket.sensitive.is_(False))
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        if kind:
            stmt = stmt.where(SupportTicket.kind == kind)
        if category:
            stmt = stmt.where(SupportTicket.category == category)
        if assignee_admin_id:
            stmt = stmt.where(SupportTicket.assigned_to_admin_user_id == assignee_admin_id)
        if unassigned:
            stmt = stmt.where(SupportTicket.assigned_to_admin_user_id.is_(None))
        if overdue_before:
            stmt = stmt.where(
                SupportTicket.status.in_(_LIVE), SupportTicket.sla_due_at.is_not(None),
                SupportTicket.sla_due_at < overdue_before,
            )
        rows = await self.session.execute(
            stmt.order_by(SupportTicket.created_at.desc(), SupportTicket.id).limit(limit)
        )
        return list(rows.scalars())

    async def summary(self, *, include_sensitive: bool):
        stmt = select(SupportTicket.status, SupportTicket.kind, func.count()).group_by(
            SupportTicket.status, SupportTicket.kind
        ).order_by(SupportTicket.status, SupportTicket.kind)
        if not include_sensitive:
            stmt = stmt.where(SupportTicket.sensitive.is_(False))
        return [tuple(r) for r in (await self.session.execute(stmt)).all()]

    async def add_event(self, **fields) -> SupportTicketEvent:
        row = SupportTicketEvent(id=uuid.uuid4(), **fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_events(self, ticket_id, *, customer_only: bool):
        stmt = select(SupportTicketEvent).where(SupportTicketEvent.ticket_id == ticket_id)
        if customer_only:
            stmt = stmt.where(SupportTicketEvent.visibility == "CUSTOMER")
        rows = await self.session.execute(stmt.order_by(SupportTicketEvent.created_at, SupportTicketEvent.id))
        return list(rows.scalars())

    # ---------------------------------------------------------------- links

    async def application_owner(self, application_id):
        return (
            await self.session.execute(select(LoanApplication.user_id).where(LoanApplication.id == application_id))
        ).scalar_one_or_none()

    async def offer_owner(self, offer_id):
        return (
            await self.session.execute(select(LoanOffer.user_id).where(LoanOffer.id == offer_id))
        ).scalar_one_or_none()

    async def get_user(self, user_id):
        return (await self.session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    async def get_admin(self, admin_id):
        return (await self.session.execute(select(AdminUser).where(AdminUser.id == admin_id))).scalar_one_or_none()
