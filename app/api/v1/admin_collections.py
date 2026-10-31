"""Admin collections: overdue cases, their history and the agent workflow.

Agents work only the cases assigned to them; managers (COLLECTIONS_MANAGE) can
assign to others and escalate. Nothing here contacts a customer, changes a
loan, or promises anything to a customer."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import collections as dom
from app.models.admin_user import AdminUser
from app.schemas.collections import (
    AssignRequest,
    CaseDetailResponse,
    CaseResponse,
    ContactRequest,
    EscalateRequest,
    EventResponse,
    NextActionRequest,
    NoteRequest,
    SummaryResponse,
    SummaryRow,
)
from app.services.collections_factory import build_collection_service

router = APIRouter(dependencies=[Depends(limit_user("admin-collections"))])
WRITE = [Depends(limit_user("admin-collections-write", sensitive=True))]


def collections_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, dom.CollectionsNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, dom.CollectionsConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/cases", response_model=list[CaseResponse])
async def list_cases(
    case_status: dom.CaseStatus | None = Query(default=None, alias="status"),
    bucket: str | None = None,
    mine: bool = False,
    unassigned: bool = False,
    min_dpd: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_collection_service(session).list_cases(
            actor_user_id=admin.user_id,
            status=case_status.value if case_status else None,
            bucket=bucket, mine=mine, unassigned=unassigned, min_dpd=min_dpd, limit=limit,
        )
    except Exception as exc:
        raise collections_http_error(exc) from exc
    return [CaseResponse.model_validate(r) for r in rows]


@router.get("/summary", response_model=SummaryResponse)
async def summary(
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_collection_service(session).summary(actor_user_id=admin.user_id)
    except Exception as exc:
        raise collections_http_error(exc) from exc
    return SummaryResponse(
        total_cases=sum(r[2] for r in rows),
        rows=[SummaryRow(status=r[0], bucket=r[1], cases=r[2], overdue_total=r[3]) for r in rows],
    )


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
async def get_case(
    case_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        case, events = await build_collection_service(session).get_case(
            actor_user_id=admin.user_id, case_id=case_id
        )
    except Exception as exc:
        raise collections_http_error(exc) from exc
    return CaseDetailResponse(
        **CaseResponse.model_validate(case).model_dump(),
        events=[EventResponse.model_validate(e) for e in events],
    )


async def _write(session, call, **kwargs):
    try:
        case = await call(**kwargs)
        await session.commit()
        return CaseResponse.model_validate(case)
    except Exception as exc:
        await session.rollback()
        raise collections_http_error(exc) from exc


@router.post("/cases/{case_id}/assign", response_model=CaseResponse, dependencies=WRITE)
async def assign_case(
    case_id: uuid.UUID,
    payload: AssignRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_collection_service(session)
    return await _write(
        session, service.assign, actor_user_id=admin.user_id, case_id=case_id,
        assignee_admin_id=payload.assignee_admin_user_id,
        request_id=_rid(request), ip_address=client_ip(request),
    )


@router.post("/cases/{case_id}/notes", response_model=CaseResponse, dependencies=WRITE)
async def add_note(
    case_id: uuid.UUID,
    payload: NoteRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_collection_service(session)
    return await _write(
        session, service.add_note, actor_user_id=admin.user_id, case_id=case_id,
        note=payload.note, request_id=_rid(request), ip_address=client_ip(request),
    )


@router.post("/cases/{case_id}/contact-attempts", response_model=CaseResponse, dependencies=WRITE)
async def log_contact(
    case_id: uuid.UUID,
    payload: ContactRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_collection_service(session)
    return await _write(
        session, service.log_contact, actor_user_id=admin.user_id, case_id=case_id,
        channel=payload.channel, outcome=payload.outcome, note=payload.note,
        request_id=_rid(request), ip_address=client_ip(request),
    )


@router.post("/cases/{case_id}/next-action", response_model=CaseResponse, dependencies=WRITE)
async def set_next_action(
    case_id: uuid.UUID,
    payload: NextActionRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_collection_service(session)
    return await _write(
        session, service.set_next_action, actor_user_id=admin.user_id, case_id=case_id,
        action=payload.action, due_at=payload.due_at, note=payload.note,
        request_id=_rid(request), ip_address=client_ip(request),
    )


@router.post("/cases/{case_id}/escalate", response_model=CaseResponse, dependencies=WRITE)
async def escalate_case(
    case_id: uuid.UUID,
    payload: EscalateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_collection_service(session)
    return await _write(
        session, service.escalate_manually, actor_user_id=admin.user_id, case_id=case_id,
        reason=payload.reason, request_id=_rid(request), ip_address=client_ip(request),
    )
