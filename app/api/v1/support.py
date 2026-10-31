"""Customer support tickets and complaints. A customer only ever sees their
own tickets and the customer-visible part of the conversation."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.auth import get_current_user
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import support as dom
from app.models.user import User
from app.schemas.support import (
    CustomerEvent,
    CustomerTicket,
    CustomerTicketDetail,
    MessageRequest,
    TicketCreateRequest,
)
from app.services.support_factory import build_support_service

router = APIRouter(dependencies=[Depends(limit_user("support"))])
WRITE = [Depends(limit_user("support-write", sensitive=True))]


def support_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, dom.SupportNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, dom.SupportConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def _who(event) -> str:
    return {"CUSTOMER": "YOU", "ADMIN": "SUPPORT", "SYSTEM": "SYSTEM"}[event.actor_type]


def _detail(ticket, events) -> CustomerTicketDetail:
    return CustomerTicketDetail(
        **CustomerTicket.model_validate(ticket).model_dump(),
        events=[
            CustomerEvent(event_type=e.event_type, **{"from": _who(e)}, body=e.body, created_at=e.created_at)
            for e in events
        ],
    )


@router.post("/tickets", response_model=CustomerTicketDetail, status_code=status.HTTP_201_CREATED, dependencies=WRITE)
async def create_ticket(
    payload: TicketCreateRequest, request: Request,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    try:
        ticket = await service.create_ticket(
            user_id=user.id, kind=payload.kind, category=payload.category, subject=payload.subject,
            message=payload.message, loan_application_id=payload.loan_application_id,
            loan_offer_id=payload.loan_offer_id, request_id=getattr(request.state, "request_id", None),
            ip_address=client_ip(request),
        )
        await session.commit()
        ticket, events = await service.get_mine(user_id=user.id, ticket_id=ticket.id)
    except Exception as exc:
        await session.rollback()
        raise support_http_error(exc) from exc
    return _detail(ticket, events)


@router.get("/tickets", response_model=list[CustomerTicket])
async def my_tickets(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session),
):
    rows = await build_support_service(session).list_mine(user_id=user.id, limit=limit)
    return [CustomerTicket.model_validate(r) for r in rows]


@router.get("/tickets/{ticket_id}", response_model=CustomerTicketDetail)
async def my_ticket(
    ticket_id: uuid.UUID,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session),
):
    try:
        ticket, events = await build_support_service(session).get_mine(user_id=user.id, ticket_id=ticket_id)
    except Exception as exc:
        raise support_http_error(exc) from exc
    return _detail(ticket, events)


@router.post("/tickets/{ticket_id}/messages", response_model=CustomerTicketDetail, dependencies=WRITE)
async def add_message(
    ticket_id: uuid.UUID, payload: MessageRequest, request: Request,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session),
):
    service = build_support_service(session)
    try:
        await service.customer_reply(
            user_id=user.id, ticket_id=ticket_id, message=payload.message,
            request_id=getattr(request.state, "request_id", None), ip_address=client_ip(request),
        )
        await session.commit()
        ticket, events = await service.get_mine(user_id=user.id, ticket_id=ticket_id)
    except Exception as exc:
        await session.rollback()
        raise support_http_error(exc) from exc
    return _detail(ticket, events)
