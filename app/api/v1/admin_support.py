"""Admin support desk. Role rules are enforced in the service: internal notes
need SUPPORT_READ, a customer's full phone number is a separate audited call,
and sensitive tickets exist only for SUPPORT_MANAGE holders."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.api.v1.support import support_http_error
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import support as dom
from app.models.admin_user import AdminUser
from app.schemas.support import (
    AdminEvent,
    AdminTicket,
    AdminTicketDetail,
    AssignRequest,
    ContactResponse,
    EscalateRequest,
    MessageRequest,
    NoteRequest,
    PriorityRequest,
    StatusRequest,
    SummaryRow,
)
from app.services.support_factory import build_support_service

router = APIRouter(dependencies=[Depends(limit_user("admin-support"))])
WRITE = [Depends(limit_user("admin-support-write", sensitive=True))]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _admin_ticket(service, ticket) -> AdminTicket:
    return AdminTicket(**AdminTicket.model_validate(ticket).model_dump(exclude={"overdue"}),
                       overdue=service.is_overdue(ticket))


@router.get("/tickets", response_model=list[AdminTicket])
async def list_tickets(
    ticket_status: dom.Status | None = Query(default=None, alias="status"),
    kind: dom.Kind | None = None,
    category: dom.Category | None = None,
    mine: bool = False, unassigned: bool = False, overdue: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    try:
        rows = await service.list_tickets(
            actor_user_id=admin.user_id, status=ticket_status.value if ticket_status else None,
            kind=kind.value if kind else None, category=category.value if category else None,
            mine=mine, unassigned=unassigned, overdue=overdue, limit=limit,
        )
    except Exception as exc:
        raise support_http_error(exc) from exc
    return [_admin_ticket(service, r) for r in rows]


@router.get("/summary", response_model=list[SummaryRow])
async def summary(
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_support_service(session).summary(actor_user_id=admin.user_id)
    except Exception as exc:
        raise support_http_error(exc) from exc
    return [SummaryRow(status=s, kind=k, count=c) for s, k, c in rows]


@router.get("/tickets/{ticket_id}", response_model=AdminTicketDetail)
async def get_ticket(
    ticket_id: uuid.UUID, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    try:
        ticket, events, masked = await service.get_ticket(
            actor_user_id=admin.user_id, ticket_id=ticket_id, request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()  # records the audit entry for a sensitive ticket
    except Exception as exc:
        await session.rollback()
        raise support_http_error(exc) from exc
    return AdminTicketDetail(
        **_admin_ticket(service, ticket).model_dump(), customer_phone_masked=masked,
        events=[AdminEvent.model_validate(e) for e in events],
    )


@router.post("/tickets/{ticket_id}/reveal-contact", response_model=ContactResponse, dependencies=WRITE)
async def reveal_contact(
    ticket_id: uuid.UUID, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    try:
        phone = await service.reveal_contact(
            actor_user_id=admin.user_id, ticket_id=ticket_id, request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise support_http_error(exc) from exc
    return ContactResponse(phone_number=phone)


async def _act(session, service, call, **kwargs) -> AdminTicket:
    try:
        ticket = await call(**kwargs)
        await session.commit()
        return _admin_ticket(service, ticket)
    except Exception as exc:
        await session.rollback()
        raise support_http_error(exc) from exc


@router.post("/tickets/{ticket_id}/assign", response_model=AdminTicket, dependencies=WRITE)
async def assign(
    ticket_id: uuid.UUID, payload: AssignRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    return await _act(session, service, service.assign, actor_user_id=admin.user_id, ticket_id=ticket_id,
                      assignee_admin_id=payload.assignee_admin_user_id, request_id=_rid(request),
                      ip_address=client_ip(request))


@router.post("/tickets/{ticket_id}/replies", response_model=AdminTicket, dependencies=WRITE)
async def reply(
    ticket_id: uuid.UUID, payload: MessageRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    return await _act(session, service, service.reply, actor_user_id=admin.user_id, ticket_id=ticket_id,
                      message=payload.message, request_id=_rid(request), ip_address=client_ip(request))


@router.post("/tickets/{ticket_id}/notes", response_model=AdminTicket, dependencies=WRITE)
async def add_note(
    ticket_id: uuid.UUID, payload: NoteRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    return await _act(session, service, service.add_note, actor_user_id=admin.user_id, ticket_id=ticket_id,
                      note=payload.note, request_id=_rid(request), ip_address=client_ip(request))


@router.post("/tickets/{ticket_id}/status", response_model=AdminTicket, dependencies=WRITE)
async def change_status(
    ticket_id: uuid.UUID, payload: StatusRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    return await _act(session, service, service.change_status, actor_user_id=admin.user_id, ticket_id=ticket_id,
                      new_status=payload.status, note=payload.note, request_id=_rid(request),
                      ip_address=client_ip(request))


@router.post("/tickets/{ticket_id}/priority", response_model=AdminTicket, dependencies=WRITE)
async def set_priority(
    ticket_id: uuid.UUID, payload: PriorityRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    return await _act(session, service, service.set_priority, actor_user_id=admin.user_id, ticket_id=ticket_id,
                      priority=payload.priority, request_id=_rid(request), ip_address=client_ip(request))


@router.post("/tickets/{ticket_id}/escalate", response_model=AdminTicket, dependencies=WRITE)
async def escalate(
    ticket_id: uuid.UUID, payload: EscalateRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    return await _act(session, service, service.escalate, actor_user_id=admin.user_id, ticket_id=ticket_id,
                      reason=payload.reason, request_id=_rid(request), ip_address=client_ip(request))
