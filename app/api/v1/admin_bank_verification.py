from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.bank_verification import bank_http_error
from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.bank_verification import (
    AdminBankVerificationResponse,
    BankVerificationResolveRequest,
)
from app.services.bank_verification_factory import build_bank_verification_service

router = APIRouter(dependencies=[Depends(limit_user("admin-bank"))])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/users/{user_id}", response_model=list[AdminBankVerificationResponse])
async def list_user_verifications(
    user_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_bank_verification_service(session)
    try:
        rows = await service.list_for_user_admin(
            actor_user_id=admin.user_id,
            user_id=user_id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise bank_http_error(exc) from exc
    return [AdminBankVerificationResponse.from_row(r) for r in rows]


@router.get("/{verification_id}", response_model=AdminBankVerificationResponse)
async def get_verification(
    verification_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_bank_verification_service(session)
    try:
        row = await service.get_for_admin(
            actor_user_id=admin.user_id,
            verification_id=verification_id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise bank_http_error(exc) from exc
    return AdminBankVerificationResponse.from_row(row)


@router.post("/{verification_id}/resolve", response_model=AdminBankVerificationResponse, dependencies=[Depends(limit_user("admin-bank-write", sensitive=True))])
async def resolve_verification(
    verification_id: uuid.UUID,
    payload: BankVerificationResolveRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_bank_verification_service(session)
    try:
        row = await service.resolve(
            actor_user_id=admin.user_id,
            verification_id=verification_id,
            decision=payload.decision,
            reason=payload.reason,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise bank_http_error(exc) from exc
    return AdminBankVerificationResponse.from_row(row)
