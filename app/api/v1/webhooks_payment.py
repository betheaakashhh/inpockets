"""Payment provider callbacks. Unauthenticated by design: authenticity is the
provider's signature, verified before anything is stored. A callback can only
report on a payment we already recorded; it can never create one."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limit_ip
from app.db.session import get_db_session
from app.domain.repayment import RepaymentConflict, RepaymentNotFound
from app.providers.payment import PaymentCallbackMalformed, PaymentSignatureInvalid
from app.services.repayment_factory import build_repayment_service

router = APIRouter(dependencies=[Depends(limit_ip("webhook-payment"))])

MAX_BODY_BYTES = 1024 * 1024


@router.post("/payment/{provider}")
async def payment_callback(
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

    service = build_repayment_service(session)
    try:
        result = await service.handle_webhook(
            provider_name=provider, headers=request.headers, body=body
        )
        await session.commit()
    except PaymentSignatureInvalid as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature") from exc
    except PaymentCallbackMalformed as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed callback") from exc
    except RepaymentNotFound as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown reference") from exc
    except RepaymentConflict as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Conflicting state") from exc
    except Exception:
        await session.rollback()
        raise
    return {"status": "ok", "outcome": result.outcome}
