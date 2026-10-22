from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain.disbursement import (
    DisbursementConflict,
    DisbursementNotFound,
    DisbursementUnavailable,
)
from app.models.user import User
from app.schemas.disbursement import DisbursementResponse
from app.services.disbursement_factory import build_disbursement_service

router = APIRouter(dependencies=[Depends(limit_user("disbursement"))])


def disbursement_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DisbursementNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Disbursement not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, DisbursementConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, DisbursementUnavailable):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Payment provider is unavailable; please retry",
            headers={"Retry-After": "30"},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


# Read-only by design: a customer can never report, confirm or trigger a payout.
@router.get("/{offer_id}/disbursement", response_model=DisbursementResponse)
async def get_my_disbursement(
    offer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_disbursement_service(session)
    try:
        d = await service.get_for_customer(actor_user_id=current_user.id, offer_id=offer_id)
    except Exception as exc:
        raise disbursement_http_error(exc) from exc
    return DisbursementResponse.from_row(d)
