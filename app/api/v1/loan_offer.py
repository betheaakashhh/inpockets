from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip, to_http_error
from app.core.auth import get_current_user
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain.loan_offer import LoanOfferStatus
from app.models.user import User
from app.schemas.loan_offer import LoanOfferAcceptRequest, LoanOfferResponse
from app.services.document import DocumentService
from app.services.loan_offer_factory import build_loan_offer_service

router = APIRouter(dependencies=[Depends(limit_user("offers"))])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("", response_model=list[LoanOfferResponse])
async def list_my_offers(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    offers = await service.list_for_customer(actor_user_id=current_user.id)
    return [LoanOfferResponse.from_offer(o) for o in offers]


@router.get("/{offer_id}", response_model=LoanOfferResponse)
async def get_my_offer(
    offer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offer = await service.get_for_customer(
            actor_user_id=current_user.id,
            offer_id=offer_id,
        )
    except Exception as exc:
        raise to_http_error(exc) from exc
    return LoanOfferResponse.from_offer(offer)


async def _serve_document(
    *,
    kind: str,
    offer_id: uuid.UUID,
    request: Request,
    current_user: User,
    session: AsyncSession,
) -> Response:
    service = build_loan_offer_service(session)
    try:
        offer = await service.get_for_customer(
            actor_user_id=current_user.id,
            offer_id=offer_id,
        )
        document_id = (
            offer.kfs_document_id if kind == "KFS" else offer.agreement_document_id
        )
        if document_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not available")

        document, content = await DocumentService(session).get_document_for_owner(
            document_id=document_id,
            owner_type="USER",
            owner_id=current_user.id,
        )
        await service.record_document_view(
            actor_user_id=current_user.id,
            offer=offer,
            document_kind=kind,
            document_id=document.id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        # A missing/unreadable document is a server-side problem, but the
        # customer-facing message stays generic.
        raise to_http_error(exc) from exc

    return Response(
        content=content.content,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{kind.lower()}-v{offer.version}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Document-Checksum": document.checksum,
        },
    )


@router.get("/{offer_id}/kfs")
async def download_kfs(
    offer_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await _serve_document(
        kind="KFS",
        offer_id=offer_id,
        request=request,
        current_user=current_user,
        session=session,
    )


@router.get("/{offer_id}/agreement")
async def download_agreement(
    offer_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await _serve_document(
        kind="AGREEMENT",
        offer_id=offer_id,
        request=request,
        current_user=current_user,
        session=session,
    )


@router.post("/{offer_id}/accept", response_model=LoanOfferResponse, dependencies=[Depends(limit_user("offers-write", sensitive=True))])
async def accept_offer(
    offer_id: uuid.UUID,
    payload: LoanOfferAcceptRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offer = await service.accept_offer(
            actor_user_id=current_user.id,
            offer_id=offer_id,
            expected_version=payload.offer_version,
            kfs_document_id=payload.kfs_document_id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        # Persist first: an expiry discovered during acceptance must stick.
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise to_http_error(exc) from exc

    if offer.status != LoanOfferStatus.ACCEPTED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This offer has expired and can no longer be accepted",
        )
    return LoanOfferResponse.from_offer(offer)


@router.post("/{offer_id}/decline", response_model=LoanOfferResponse, dependencies=[Depends(limit_user("offers-write", sensitive=True))])
async def decline_offer(
    offer_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_loan_offer_service(session)
    try:
        offer = await service.decline_offer(
            actor_user_id=current_user.id,
            offer_id=offer_id,
            request_id=_request_id(request),
            ip_address=client_ip(request),
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise to_http_error(exc) from exc
    return LoanOfferResponse.from_offer(offer)
