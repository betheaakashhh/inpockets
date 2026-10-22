from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.disbursement import disbursement_http_error
from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain.disbursement import DisbursementConflict, DisbursementUnavailable
from app.models.admin_user import AdminUser
from app.schemas.disbursement import (
    AdminDisbursementResponse,
    DisbursementCreateRequest,
    DisbursementRecheckResponse,
    DisbursementRetryRequest,
)
from app.services.disbursement_factory import build_disbursement_service

router = APIRouter(dependencies=[Depends(limit_user("admin-disbursement"))])
WRITE = [Depends(limit_user("admin-disbursement-write", sensitive=True))]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post(
    "",
    response_model=AdminDisbursementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=WRITE,
)
async def create_disbursement(
    payload: DisbursementCreateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_disbursement_service(session)
    try:
        d = await service.create_for_offer(
            actor_user_id=admin.user_id,
            offer_id=payload.loan_offer_id,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise disbursement_http_error(exc) from exc
    return AdminDisbursementResponse.from_row(d)


@router.get("", response_model=list[AdminDisbursementResponse])
async def list_disbursements(
    status_filter: str | None = Query(default=None, alias="status"),
    loan_offer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_disbursement_service(session)
    try:
        rows = await service.list_for_admin(
            actor_user_id=admin.user_id,
            status=status_filter,
            loan_offer_id=loan_offer_id,
            limit=limit,
        )
    except Exception as exc:
        raise disbursement_http_error(exc) from exc
    return [AdminDisbursementResponse.from_row(d) for d in rows]


@router.get("/{disbursement_id}", response_model=AdminDisbursementResponse)
async def get_disbursement(
    disbursement_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_disbursement_service(session)
    try:
        d, events = await service.get_for_admin(
            actor_user_id=admin.user_id, disbursement_id=disbursement_id
        )
    except Exception as exc:
        raise disbursement_http_error(exc) from exc
    return AdminDisbursementResponse.from_row(d, events)


@router.post(
    "/{disbursement_id}/retry",
    response_model=AdminDisbursementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=WRITE,
)
async def retry_disbursement(
    disbursement_id: uuid.UUID,
    payload: DisbursementRetryRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_disbursement_service(session)
    try:
        d = await service.retry(
            actor_user_id=admin.user_id,
            disbursement_id=disbursement_id,
            reason=payload.reason,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except DisbursementConflict as exc:
        # A refused retry may still have moved the old payout into review.
        if getattr(exc, "persist", False):
            await session.commit()
        else:
            await session.rollback()
        raise disbursement_http_error(exc) from exc
    except Exception as exc:
        await session.rollback()
        raise disbursement_http_error(exc) from exc
    return AdminDisbursementResponse.from_row(d)


@router.post(
    "/{disbursement_id}/recheck",
    response_model=DisbursementRecheckResponse,
    dependencies=WRITE,
)
async def recheck_disbursement(
    disbursement_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_disbursement_service(session)
    try:
        d, outcome = await service.recheck(
            actor_user_id=admin.user_id,
            disbursement_id=disbursement_id,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except DisbursementUnavailable as exc:
        await session.rollback()
        raise disbursement_http_error(exc) from exc
    except Exception as exc:
        await session.rollback()
        raise disbursement_http_error(exc) from exc
    return DisbursementRecheckResponse(
        outcome=outcome, disbursement=AdminDisbursementResponse.from_row(d)
    )
