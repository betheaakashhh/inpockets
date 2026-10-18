from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip, to_http_error
from app.core.admin import get_current_admin
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.loan_offer import (
    AdminLoanOfferResponse,
    LoanOfferCancelRequest,
    LoanOfferDraftCreateRequest,
    LoanOfferIssueRequest,
)
from app.services.loan_offer_factory import (
    build_loan_offer_issuance_service,
    build_loan_offer_service,
)

router = APIRouter()


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post(
    "",
    response_model=AdminLoanOfferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft_offer(
    payload: LoanOfferDraftCreateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offer = await service.create_draft(
            actor_user_id=admin.user_id,
            loan_application_id=payload.loan_application_id,
            principal_amount=payload.principal_amount,
            tenure_days=payload.tenure_days,
            commercial_terms=payload.commercial_terms,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return AdminLoanOfferResponse.from_offer(offer)
    except Exception as exc:
        await session.rollback()
        raise to_http_error(exc) from exc


@router.get("", response_model=list[AdminLoanOfferResponse])
async def list_offers_for_application(
    loan_application_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offers = await service.list_for_application_admin(
            actor_user_id=admin.user_id,
            loan_application_id=loan_application_id,
        )
    except Exception as exc:
        raise to_http_error(exc) from exc
    return [AdminLoanOfferResponse.from_offer(o) for o in offers]


@router.get("/{offer_id}", response_model=AdminLoanOfferResponse)
async def get_offer(
    offer_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offer = await service.get_for_admin(
            actor_user_id=admin.user_id,
            offer_id=offer_id,
        )
    except Exception as exc:
        raise to_http_error(exc) from exc
    return AdminLoanOfferResponse.from_offer(offer)


@router.post("/{offer_id}/issue", response_model=AdminLoanOfferResponse)
async def issue_offer(
    offer_id: uuid.UUID,
    request: Request,
    payload: LoanOfferIssueRequest | None = None,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Generate KFS + agreement from the draft's terms and issue the offer."""
    payload = payload or LoanOfferIssueRequest()
    issuance = build_loan_offer_issuance_service(session)
    try:
        offer = await issuance.issue(
            actor_user_id=admin.user_id,
            offer_id=offer_id,
            validity=payload.validity(),
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return AdminLoanOfferResponse.from_offer(offer)
    except Exception as exc:
        await session.rollback()
        raise to_http_error(exc) from exc


@router.post("/{offer_id}/cancel", response_model=AdminLoanOfferResponse)
async def cancel_offer(
    offer_id: uuid.UUID,
    payload: LoanOfferCancelRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offer = await service.cancel_offer(
            actor_user_id=admin.user_id,
            offer_id=offer_id,
            reason=payload.reason,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
        return AdminLoanOfferResponse.from_offer(offer)
    except Exception as exc:
        await session.rollback()
        raise to_http_error(exc) from exc
