"""Admin notifications: templates (maker-checker), history, dead letters."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.api.v1.notifications import notification_http_error
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import notifications as dom
from app.models.admin_user import AdminUser
from app.schemas.notifications import (
    AdminNotificationDetail,
    AdminNotificationResponse,
    AttemptResponse,
    RequeueRequest,
    StatusCount,
    TemplateCreateRequest,
    TemplateResponse,
)
from app.services.notifications_factory import build_notification_service

router = APIRouter(dependencies=[Depends(limit_user("admin-notifications"))])
WRITE = [Depends(limit_user("admin-notifications-write", sensitive=True))]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED, dependencies=WRITE)
async def create_template(
    payload: TemplateCreateRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_notification_service(session)
    try:
        row = await service.create_template(
            actor_user_id=admin.user_id, template_key=payload.template_key, channel=payload.channel,
            body=payload.body, allowed_variables=payload.allowed_variables, subject=payload.subject,
            locale=payload.locale, request_id=_rid(request), ip_address=client_ip(request),
        )
        await session.commit()
        return TemplateResponse.model_validate(row)
    except Exception as exc:
        await session.rollback()
        raise notification_http_error(exc) from exc


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    key: str | None = None,
    template_status: dom.TemplateStatus | None = Query(default=None, alias="status"),
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_notification_service(session).list_templates(
            actor_user_id=admin.user_id, key=key, status=template_status.value if template_status else None
        )
    except Exception as exc:
        raise notification_http_error(exc) from exc
    return [TemplateResponse.model_validate(r) for r in rows]


async def _decide(template_id, approve, request, admin, session):
    service = build_notification_service(session)
    try:
        row = await service.decide_template(
            actor_user_id=admin.user_id, template_id=template_id, approve=approve,
            request_id=_rid(request), ip_address=client_ip(request),
        )
        await session.commit()
        return TemplateResponse.model_validate(row)
    except Exception as exc:
        await session.rollback()
        raise notification_http_error(exc) from exc


@router.post("/templates/{template_id}/approve", response_model=TemplateResponse, dependencies=WRITE)
async def approve_template(
    template_id: uuid.UUID, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    return await _decide(template_id, True, request, admin, session)


@router.post("/templates/{template_id}/reject", response_model=TemplateResponse, dependencies=WRITE)
async def reject_template(
    template_id: uuid.UUID, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    return await _decide(template_id, False, request, admin, session)


@router.get("/summary", response_model=list[StatusCount])
async def summary(
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_notification_service(session).status_counts(actor_user_id=admin.user_id)
    except Exception as exc:
        raise notification_http_error(exc) from exc
    return [StatusCount(status=s, count=c) for s, c in rows]


@router.get("", response_model=list[AdminNotificationResponse])
async def list_notifications(
    notification_status: dom.Status | None = Query(default=None, alias="status"),
    channel: dom.Channel | None = None,
    template_key: str | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_notification_service(session).list_notifications(
            actor_user_id=admin.user_id,
            status=notification_status.value if notification_status else None,
            channel=channel.value if channel else None,
            template_key=template_key, user_id=user_id, limit=limit,
        )
    except Exception as exc:
        raise notification_http_error(exc) from exc
    return [AdminNotificationResponse.model_validate(r) for r in rows]


@router.get("/{notification_id}", response_model=AdminNotificationDetail)
async def get_notification(
    notification_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    try:
        n, attempts = await build_notification_service(session).get_notification(
            actor_user_id=admin.user_id, notification_id=notification_id
        )
    except Exception as exc:
        raise notification_http_error(exc) from exc
    return AdminNotificationDetail(
        **AdminNotificationResponse.model_validate(n).model_dump(),
        attempts_log=[AttemptResponse.model_validate(a) for a in attempts],
    )


@router.post("/{notification_id}/requeue", response_model=AdminNotificationResponse, dependencies=WRITE)
async def requeue(
    notification_id: uuid.UUID, payload: RequeueRequest, request: Request,
    admin: AdminUser = Depends(get_current_admin), session: AsyncSession = Depends(get_db_session),
):
    service = build_notification_service(session)
    try:
        n = await service.requeue_dead(
            actor_user_id=admin.user_id, notification_id=notification_id, reason=payload.reason,
            request_id=_rid(request), ip_address=client_ip(request),
        )
        await session.commit()
        return AdminNotificationResponse.model_validate(n)
    except Exception as exc:
        await session.rollback()
        raise notification_http_error(exc) from exc
