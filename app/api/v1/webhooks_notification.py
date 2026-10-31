"""Notification delivery receipts. Unauthenticated by design: authenticity is
the provider's signature, verified before anything is stored. A receipt can
only update a notification we already sent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limit_ip
from app.db.session import get_db_session
from app.providers.notification import NotificationCallbackMalformed, NotificationSignatureInvalid
from app.services.notifications_factory import build_notification_service

router = APIRouter(dependencies=[Depends(limit_ip("webhook-notification"))])
MAX_BODY_BYTES = 1024 * 1024


@router.post("/notification/{provider}")
async def notification_receipt(
    provider: str, request: Request, session: AsyncSession = Depends(get_db_session),
):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body too large")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body too large")
    service = build_notification_service(session)
    try:
        result = await service.handle_receipt(provider_name=provider, headers=request.headers, body=body)
        await session.commit()
    except NotificationSignatureInvalid as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature") from exc
    except NotificationCallbackMalformed as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed callback") from exc
    except Exception:
        await session.rollback()
        raise
    return {"status": "ok", "outcome": result.outcome}
