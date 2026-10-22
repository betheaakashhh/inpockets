from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.esign import esign_http_error
from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.esign import AdminESignResponse, ESignReviewResolveRequest
from app.services.esign_factory import build_esign_service

router = APIRouter(dependencies=[Depends(limit_user("admin-esign"))])


@router.get("/{offer_id}/esign", response_model=AdminESignResponse)
async def admin_get_esign(
    offer_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        tx, events = await service.get_for_admin(
            actor_user_id=admin.user_id, offer_id=offer_id
        )
    except Exception as exc:
        raise esign_http_error(exc) from exc
    return AdminESignResponse.from_tx(tx, events)


@router.get("/esign/review-queue", response_model=list[AdminESignResponse])
async def esign_review_queue(
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        rows = await service.list_review_queue(actor_user_id=admin.user_id)
    except Exception as exc:
        raise esign_http_error(exc) from exc
    return [AdminESignResponse.from_tx(tx, []) for tx in rows]


@router.post(
    "/{offer_id}/esign/resolve",
    response_model=AdminESignResponse,
    dependencies=[Depends(limit_user("admin-esign-write", sensitive=True))],
)
async def resolve_esign_review(
    offer_id: uuid.UUID,
    payload: ESignReviewResolveRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        tx = await service.resolve_review(
            actor_user_id=admin.user_id,
            offer_id=offer_id,
            decision=payload.decision,
            reason=payload.reason,
            request_id=getattr(request.state, "request_id", None),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise esign_http_error(exc) from exc
    return AdminESignResponse.from_tx(tx, [])
