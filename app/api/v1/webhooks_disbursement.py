"""Disbursement provider callbacks. Unauthenticated by design: authenticity is
the provider's signature, verified before anything is stored. A callback never
creates money movement; it can only report on a payout we already recorded."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limit_ip
from app.db.session import get_db_session
from app.domain.disbursement import DisbursementConflict, DisbursementNotFound
from app.providers.disbursement import (
    DisbursementCallbackMalformed,
    DisbursementSignatureInvalid,
)
from app.services.disbursement_factory import build_disbursement_service

router = APIRouter(dependencies=[Depends(limit_ip("webhook-disbursement"))])

MAX_BODY_BYTES = 1024 * 1024


@router.post("/disbursement/{provider}")
async def disbursement_callback(
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
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body too large")

    service = build_disbursement_service(session)
    try:
        result = await service.handle_webhook(
            provider_name=provider, headers=request.headers, body=body
        )
        await session.commit()
    except DisbursementSignatureInvalid as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature") from exc
    except DisbursementCallbackMalformed as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed callback") from exc
    except DisbursementNotFound as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown reference") from exc
    except DisbursementConflict as exc:
        # Contradictory state we could not apply: let the provider retry, a
        # human can look at the rolled-back event in the provider's dashboard.
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Conflicting state") from exc
    except Exception:
        await session.rollback()
        raise
    return {"status": "ok", "outcome": result.outcome}
