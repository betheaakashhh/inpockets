from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.auth import get_current_user
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain.ledger import LedgerConflict, LedgerNotFound
from app.domain.repayment import RepaymentConflict, RepaymentNotFound, RepaymentUnavailable
from app.models.user import User
from app.schemas.repayment import PaymentCreateRequest, PaymentResponse, ScheduleResponse
from app.services.repayment_factory import build_repayment_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(limit_user("repayment"))])
WRITE = [Depends(limit_user("repayment-write", sensitive=True))]


def repayment_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (RepaymentNotFound, LedgerNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc) or "Not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, (RepaymentConflict, LedgerConflict)):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, RepaymentUnavailable):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Payment provider is unavailable; please retry",
            headers={"Retry-After": "30"},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


@router.get("/{offer_id}/repayment-schedule", response_model=ScheduleResponse)
async def get_my_schedule(
    offer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        schedule, installments = await service.get_schedule_for_customer(
            actor_user_id=current_user.id, offer_id=offer_id
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return ScheduleResponse.from_rows(schedule, installments)


@router.post(
    "/{offer_id}/repayments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=WRITE,
)
async def start_repayment(
    offer_id: uuid.UUID,
    payload: PaymentCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Open a payment. Success is never reported by the client: the payment
    becomes PAID only when the provider confirms it (signed webhook or our own
    lookup), and the response here only ever says PROCESSING (or FAILED)."""
    service = build_repayment_service(session)
    user_id = current_user.id  # read before commits/expiry touch the ORM object
    try:
        payment, created = await service.initiate_payment(
            actor_user_id=user_id,
            offer_id=offer_id,
            amount=payload.amount,
            client_key=idempotency_key,
            request_id=getattr(request.state, "request_id", None),
            ip_address=client_ip(request),
        )
        payment_id = payment.id
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise repayment_http_error(exc) from exc

    if not created:
        response.status_code = status.HTTP_200_OK
    # Second transaction: the provider is contacted only after the attempt is
    # durably recorded, and a failure here never loses it (the worker retries).
    try:
        await service.dispatch_payment(payment_id)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("repayment dispatch failed id=%s", payment_id)
    session.expire_all()
    payment = await service.get_payment_for_customer(actor_user_id=user_id, payment_id=payment_id)
    return PaymentResponse.from_row(payment)


@router.get("/{offer_id}/repayments", response_model=list[PaymentResponse])
async def list_my_repayments(
    offer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        rows = await service.list_payments_for_customer(
            actor_user_id=current_user.id, offer_id=offer_id
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return [PaymentResponse.from_row(p) for p in rows]


@router.get("/{offer_id}/repayments/{payment_id}", response_model=PaymentResponse)
async def get_my_repayment(
    offer_id: uuid.UUID,
    payment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_repayment_service(session)
    try:
        p = await service.get_payment_for_customer(
            actor_user_id=current_user.id, payment_id=payment_id
        )
        if p.loan_offer_id != offer_id:
            raise RepaymentNotFound("Payment not found")
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return PaymentResponse.from_row(p)
