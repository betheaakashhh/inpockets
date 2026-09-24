from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin import get_current_admin, get_current_loan_admin
from app.db.session import get_db_session
from app.domain.loan_application import LoanApplicationStatus
from app.models.admin_user import AdminUser
from app.repositories.loan_application import LoanApplicationRepository
from app.schemas.admin_loan_application import (
    AdminLoanApplicationEventResponse,
    AdminLoanApplicationResponse,
    AdminLoanApplicationTransitionRequest,
)
from app.services.loan_application import LoanApplicationService


router = APIRouter()


def get_loan_application_service(
    session: AsyncSession = Depends(get_db_session),
) -> LoanApplicationService:
    return LoanApplicationService(LoanApplicationRepository(session))


@router.get(
    "",
    response_model=list[AdminLoanApplicationResponse],
)
async def list_loan_applications(
    user_id: uuid.UUID | None = None,
    _admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[AdminLoanApplicationResponse]:
    repository = LoanApplicationRepository(session)

    if user_id is not None:
        applications = await repository.list_by_user_id(user_id=user_id)
        return applications

    # Keep the first admin API intentionally scoped.
    # A paginated/searchable operational queue will be added with
    # underwriting/admin workflow hardening.
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="user_id is required",
    )


@router.get(
    "/{application_id}",
    response_model=AdminLoanApplicationResponse,
)
async def get_loan_application(
    application_id: uuid.UUID,
    _admin: AdminUser = Depends(get_current_admin),
    service: LoanApplicationService = Depends(get_loan_application_service),
):
    application = await service.repository.get_by_id(
        application_id=application_id,
    )

    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Loan application not found",
        )

    return application


@router.post(
    "/{application_id}/process",
    response_model=AdminLoanApplicationResponse,
)
async def process_loan_application(
    application_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_loan_admin),
    session: AsyncSession = Depends(get_db_session),
    service: LoanApplicationService = Depends(get_loan_application_service),
):
    try:
        application = await service.transition_status(
            application_id=application_id,
            next_status=LoanApplicationStatus.PROCESSING,
            actor_type="ADMIN",
            actor_id=admin.id,
            reason="Application moved to processing.",
        )

        await session.commit()
        return application

    except ValueError as exc:
        await session.rollback()
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Loan application not found",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from exc


@router.post(
    "/{application_id}/transition",
    response_model=AdminLoanApplicationResponse,
)
async def transition_loan_application(
    application_id: uuid.UUID,
    payload: AdminLoanApplicationTransitionRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_loan_admin),
    session: AsyncSession = Depends(get_db_session),
    service: LoanApplicationService = Depends(get_loan_application_service),
):
    try:
        application = await service.transition_status(
            application_id=application_id,
            next_status=payload.status,
            actor_type="ADMIN",
            actor_id=admin.id,
            reason=payload.reason,
        )

        await session.commit()
        return application

    except ValueError as exc:
        await session.rollback()
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Loan application not found",
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from exc


@router.get(
    "/{application_id}/events",
    response_model=list[AdminLoanApplicationEventResponse],
)
async def get_loan_application_events(
    application_id: uuid.UUID,
    _admin: AdminUser = Depends(get_current_admin),
    service: LoanApplicationService = Depends(get_loan_application_service),
):
    application = await service.repository.get_by_id(
        application_id=application_id,
    )

    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Loan application not found",
        )

    return await service.repository.list_events(
        application_id=application_id,
    )