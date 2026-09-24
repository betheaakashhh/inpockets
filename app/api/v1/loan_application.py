from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.repositories.loan_application import LoanApplicationRepository
from app.schemas.loan_application import (
    LoanApplicationCreateRequest,
    LoanApplicationEventResponse,
    LoanApplicationResponse,
)
from app.services.loan_application import LoanApplicationService


router = APIRouter()


def _get_service(session: AsyncSession) -> LoanApplicationService:
    repository = LoanApplicationRepository(session)
    return LoanApplicationService(repository)


@router.post(
    "",
    response_model=LoanApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_loan_application(
    request: LoanApplicationCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _get_service(session)

    try:
        application = await service.create_draft(
            user_id=current_user.id,
            requested_amount=request.requested_amount,
            requested_tenure_days=request.requested_tenure_days,
        )

        await session.commit()

        return application

    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[LoanApplicationResponse],
)
async def list_loan_applications(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _get_service(session)

    return await service.list_user_applications(
        user_id=current_user.id,
    )


@router.get(
    "/{application_id}",
    response_model=LoanApplicationResponse,
)
async def get_loan_application(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _get_service(session)

    try:
        return await service.get_application(
            application_id=application_id,
            user_id=current_user.id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Loan application not found",
        ) from exc


@router.post(
    "/{application_id}/submit",
    response_model=LoanApplicationResponse,
)
async def submit_loan_application(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _get_service(session)

    try:
        application = await service.submit(
            application_id=application_id,
            user_id=current_user.id,
        )

        await session.commit()

        return application

    except ValueError as exc:
        await session.rollback()

        if "not found" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Loan application not found",
            ) from exc

        if "does not belong" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Loan application not found",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{application_id}/events",
    response_model=list[LoanApplicationEventResponse],
)
async def get_loan_application_events(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = _get_service(session)

    try:
        return await service.get_events(
            application_id=application_id,
            user_id=current_user.id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Loan application not found",
        ) from exc