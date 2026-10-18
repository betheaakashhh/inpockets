from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.domain.esign import ESignConflict, ESignNotFound, ESignUnavailable
from app.models.user import User
from app.schemas.esign import ESignResponse
from app.services.esign_factory import build_esign_service

router = APIRouter()


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def esign_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ESignNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, ESignConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ESignUnavailable):
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "E-sign provider is unavailable; please retry",
            headers={"Retry-After": "30"},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


@router.post("/{offer_id}/esign", response_model=ESignResponse)
async def initiate_esign(
    offer_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        tx, url = await service.initiate(
            actor_user_id=current_user.id,
            offer_id=offer_id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return ESignResponse.from_tx(tx, url)
    except ESignUnavailable as exc:
        # Keep the INITIATED row: a retry reuses the same client reference.
        await session.commit()
        raise esign_http_error(exc) from exc
    except Exception as exc:
        await session.rollback()
        raise esign_http_error(exc) from exc


@router.get("/{offer_id}/esign", response_model=ESignResponse)
async def get_esign_status(
    offer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        tx, url = await service.get_for_customer(
            actor_user_id=current_user.id, offer_id=offer_id
        )
    except Exception as exc:
        raise esign_http_error(exc) from exc
    return ESignResponse.from_tx(tx, url)


@router.get("/{offer_id}/signed-agreement")
async def download_signed_agreement(
    offer_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_esign_service(session)
    try:
        _, doc, content = await service.get_signed_document(
            actor_user_id=current_user.id,
            offer_id=offer_id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise esign_http_error(exc) from exc
    return Response(
        content=content.content,
        media_type=doc.content_type,
        headers={
            "Content-Disposition": 'inline; filename="signed-agreement.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Document-Checksum": doc.checksum,
        },
    )
