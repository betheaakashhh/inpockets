"""Provider callback endpoint. Unauthenticated by design: authenticity comes
from the provider's signature, verified before anything is read or stored."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.domain.esign import ESignNotFound, ESignUnavailable
from app.providers.esign import ESignCallbackMalformed, ESignSignatureInvalid
from app.services.esign_factory import build_esign_service

router = APIRouter()

MAX_BODY_BYTES = 25 * 1024 * 1024  # signed PDFs may ride in the callback


@router.post("/esign/{provider}")
async def esign_callback(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body too large")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body too large"
            )

    service = build_esign_service(session)
    try:
        result = await service.handle_callback(
            provider_name=provider, headers=request.headers, body=body
        )
        await session.commit()
    except ESignSignatureInvalid as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature") from exc
    except ESignCallbackMalformed as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed callback") from exc
    except ESignNotFound as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown reference") from exc
    except ESignUnavailable as exc:
        # Roll back (including the event row) so the provider retries.
        await session.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Temporarily unavailable"
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return {"status": "ok", "outcome": result.outcome}
