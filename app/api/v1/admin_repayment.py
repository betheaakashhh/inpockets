from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.api.v1.repayment import repayment_http_error
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.repayment import (
    AdminPaymentResponse,
    AdminScheduleResponse,
    PaymentRecheckResponse,
    ScheduleCancelRequest,
    ScheduleCreateRequest,
    ScheduleResponse,
)
from app.services.repayment_factory import build_repayment_service

router = APIRouter(dependencies=[Depends(limit_user("admin-repayment"))])
WRITE = [Depends(limit_user("admin-repayment-write", sensitive=True))]


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _admin_schedule(service, admin, schedule_id) -> AdminScheduleResponse:
    schedule, installments, ledger_principal = await service.get_schedule_for_admin(
        actor_user_id=admin.user_id, schedule_id=schedule_id
    )
    return AdminScheduleResponse.from_admin_rows(schedule, installments, ledger_principal)


@router.post(
    "/schedules",
    response_model=AdminScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=WRITE,
)
async def create_schedule(
    payload: ScheduleCreateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        schedule = await service.create_schedule(
            actor_user_id=admin.user_id,
            offer_id=payload.loan_offer_id,
            installment_count=payload.installment_count,
            interval_days=payload.interval_days,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        schedule_id = schedule.id
        await session.commit()
        return await _admin_schedule(service, admin, schedule_id)
    except Exception as exc:
        await session.rollback()
        raise repayment_http_error(exc) from exc


@router.get("/schedules", response_model=list[ScheduleResponse])
async def list_schedules(
    loan_offer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        rows = await service.list_schedules_for_admin(
            actor_user_id=admin.user_id, loan_offer_id=loan_offer_id, limit=limit
        )
        out = []
        for s in rows:
            out.append(ScheduleResponse.from_rows(s, await service.repository.list_installments(s.id)))
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return out


@router.get("/schedules/{schedule_id}", response_model=AdminScheduleResponse)
async def get_schedule(
    schedule_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        return await _admin_schedule(service, admin, schedule_id)
    except Exception as exc:
        raise repayment_http_error(exc) from exc


@router.post(
    "/schedules/{schedule_id}/activate", response_model=AdminScheduleResponse, dependencies=WRITE
)
async def activate_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        await service.activate_schedule(
            actor_user_id=admin.user_id,
            schedule_id=schedule_id,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return await _admin_schedule(service, admin, schedule_id)
    except Exception as exc:
        await session.rollback()
        raise repayment_http_error(exc) from exc


@router.post(
    "/schedules/{schedule_id}/cancel", response_model=AdminScheduleResponse, dependencies=WRITE
)
async def cancel_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleCancelRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        await service.cancel_schedule(
            actor_user_id=admin.user_id,
            schedule_id=schedule_id,
            reason=payload.reason,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return await _admin_schedule(service, admin, schedule_id)
    except Exception as exc:
        await session.rollback()
        raise repayment_http_error(exc) from exc


@router.get("/payments", response_model=list[AdminPaymentResponse])
async def list_payments(
    status_filter: str | None = Query(default=None, alias="status"),
    loan_offer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        rows = await service.list_payments_for_admin(
            actor_user_id=admin.user_id, status=status_filter, loan_offer_id=loan_offer_id, limit=limit
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return [AdminPaymentResponse.from_row(p) for p in rows]


@router.get("/payments/{payment_id}", response_model=AdminPaymentResponse)
async def get_payment(
    payment_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        p, events = await service.get_payment_for_admin(
            actor_user_id=admin.user_id, payment_id=payment_id
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return AdminPaymentResponse.from_row(p, events)


@router.post(
    "/payments/{payment_id}/recheck", response_model=PaymentRecheckResponse, dependencies=WRITE
)
async def recheck_payment(
    payment_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        p, outcome = await service.recheck(
            actor_user_id=admin.user_id,
            payment_id=payment_id,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise repayment_http_error(exc) from exc
    return PaymentRecheckResponse(outcome=outcome, payment=AdminPaymentResponse.from_row(p))
