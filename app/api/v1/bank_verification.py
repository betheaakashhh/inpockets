from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.auth import get_current_user
from app.core.rate_limit import limit_user
from app.core.encryption import EncryptionError
from app.db.session import get_db_session
from app.domain.bank_verification import (
    BankVerificationConflict,
    BankVerificationNotFound,
    BankVerificationRateLimited,
    BankVerificationUnavailable,
)
from app.models.user import User
from app.schemas.bank_verification import (
    BankVerificationRequest,
    BankVerificationResponse,
)
from app.services.bank_verification_factory import build_bank_verification_service

router = APIRouter(dependencies=[Depends(limit_user("bank"))])
logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def bank_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BankVerificationNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Bank verification not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    if isinstance(exc, BankVerificationConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, BankVerificationRateLimited):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": "3600"}
        )
    if isinstance(exc, BankVerificationUnavailable):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Bank verification is temporarily unavailable; please retry",
            headers={"Retry-After": "30"},
        )
    if isinstance(exc, EncryptionError):
        # Misconfiguration: log the class only, tell the client nothing.
        logger.error("bank verification encryption failure: %s", type(exc).__name__)
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Service unavailable")
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


@router.post("", response_model=BankVerificationResponse, dependencies=[Depends(limit_user("bank-write", sensitive=True))])
async def request_bank_verification(
    payload: BankVerificationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_bank_verification_service(session)
    try:
        row = await service.request(
            actor_user_id=current_user.id,
            account_number=payload.account_number.get_secret_value(),
            ifsc=payload.ifsc,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return BankVerificationResponse.from_row(row)
    except BankVerificationUnavailable as exc:
        # Keep the INITIATED row: a retry reuses the same client reference.
        await session.commit()
        raise bank_http_error(exc) from exc
    except Exception as exc:
        await session.rollback()
        raise bank_http_error(exc) from exc


@router.get("/current", response_model=BankVerificationResponse)
async def get_current_bank_verification(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_bank_verification_service(session)
    try:
        row = await service.get_current_for_customer(actor_user_id=current_user.id)
    except Exception as exc:
        raise bank_http_error(exc) from exc
    return BankVerificationResponse.from_row(row)
