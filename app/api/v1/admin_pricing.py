from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import pricing as dom
from app.models.admin_user import AdminUser
from app.schemas.pricing import (
    PricingRejectRequest,
    PricingVersionCreateRequest,
    PricingVersionResponse,
)
from app.services.pricing_factory import build_pricing_service

router = APIRouter(dependencies=[Depends(limit_user("admin-pricing"))])
WRITE = [Depends(limit_user("admin-pricing-write", sensitive=True))]


def pricing_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, dom.PricingNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, dom.PricingConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post(
    "/versions",
    response_model=PricingVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=WRITE,
)
async def create_version(
    payload: PricingVersionCreateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_pricing_service(session)
    try:
        version = await service.create_draft(
            actor_user_id=admin.user_id,
            terms=dom.PricingTerms(
                annual_interest_percent=payload.annual_interest_percent,
                processing_fee_percent=payload.processing_fee_percent,
                gst_percent=payload.gst_percent,
            ),
            late=dom.LateTerms(
                enabled=payload.late_charges_enabled,
                bounce_percent=payload.bounce_percent,
                bounce_cap_amount=payload.bounce_cap_amount,
                penal_annual_percent=payload.penal_annual_percent,
                penal_max_days=payload.penal_max_days,
                total_cap_percent_of_due=payload.late_total_cap_percent_of_due,
            ),
            effective_from=payload.effective_from,
            note=payload.note,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return PricingVersionResponse.model_validate(version)
    except Exception as exc:
        await session.rollback()
        raise pricing_http_error(exc) from exc


@router.get("/versions", response_model=list[PricingVersionResponse])
async def list_versions(
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_pricing_service(session).list_versions(actor_user_id=admin.user_id)
    except Exception as exc:
        raise pricing_http_error(exc) from exc
    return [PricingVersionResponse.model_validate(r) for r in rows]


@router.get("/current", response_model=PricingVersionResponse | None)
async def current_version(
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row = await build_pricing_service(session).current(actor_user_id=admin.user_id)
    except Exception as exc:
        raise pricing_http_error(exc) from exc
    return None if row is None else PricingVersionResponse.model_validate(row)


@router.get("/versions/{version_id}", response_model=PricingVersionResponse)
async def get_version(
    version_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row = await build_pricing_service(session).get_version(
            actor_user_id=admin.user_id, version_id=version_id
        )
    except Exception as exc:
        raise pricing_http_error(exc) from exc
    return PricingVersionResponse.model_validate(row)


@router.post("/versions/{version_id}/approve", response_model=PricingVersionResponse, dependencies=WRITE)
async def approve_version(
    version_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_pricing_service(session)
    try:
        row = await service.approve(
            actor_user_id=admin.user_id,
            version_id=version_id,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return PricingVersionResponse.model_validate(row)
    except Exception as exc:
        await session.rollback()
        raise pricing_http_error(exc) from exc


@router.post("/versions/{version_id}/reject", response_model=PricingVersionResponse, dependencies=WRITE)
async def reject_version(
    version_id: uuid.UUID,
    payload: PricingRejectRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_pricing_service(session)
    try:
        row = await service.reject(
            actor_user_id=admin.user_id,
            version_id=version_id,
            reason=payload.reason,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return PricingVersionResponse.model_validate(row)
    except Exception as exc:
        await session.rollback()
        raise pricing_http_error(exc) from exc
