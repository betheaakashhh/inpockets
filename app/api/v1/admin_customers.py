from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin import get_current_admin
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.admin_customer import (
    AdminCustomerDetail,
    AdminCustomerListResponse,
    AdminCustomerSummary,
)
from app.services.admin_customer import AdminCustomerService


router = APIRouter()


def get_admin_customer_service(
    session: AsyncSession = Depends(get_db_session),
) -> AdminCustomerService:
    return AdminCustomerService(session)


def _summary(row) -> AdminCustomerSummary:
    user, profile, onboarding, pan_status, pan_number_masked, kyc_status = row
    return AdminCustomerSummary(
        customer_id=user.id,
        phone_number=user.phone_number,
        status=user.status,
        first_name=profile.first_name if profile else None,
        last_name=profile.last_name if profile else None,
        date_of_birth=profile.date_of_birth if profile else None,
        gender=profile.gender if profile else None,
        onboarding_status=onboarding.status if onboarding else None,
        onboarding_step=onboarding.current_step if onboarding else None,
        created_at=user.created_at,
        pan_status=pan_status,
        pan_number_masked=pan_number_masked,
        kyc_status=kyc_status,
    )


@router.get("", response_model=AdminCustomerListResponse)
async def list_customers(
    page: int = 1,
    page_size: int = 20,
    _admin: AdminUser = Depends(get_current_admin),
    service: AdminCustomerService = Depends(get_admin_customer_service),
) -> AdminCustomerListResponse:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="Invalid pagination")

    rows, total = await service.list_customers(page=page, page_size=page_size)
    return AdminCustomerListResponse(
        items=[_summary(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{customer_id}", response_model=AdminCustomerDetail)
async def get_customer(
    customer_id: UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    service: AdminCustomerService = Depends(get_admin_customer_service),
) -> AdminCustomerDetail:
    row = await service.get_customer(
        customer_id=customer_id,
        admin_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
    )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    user, profile, onboarding, _pan_status, _pan_number_masked, _kyc_status = row
    return AdminCustomerDetail(
        **_summary(row).model_dump(),
        profile_id=profile.id if profile else None,
        onboarding_id=onboarding.id if onboarding else None,
        onboarding_created_at=onboarding.created_at if onboarding else None,
        onboarding_updated_at=onboarding.updated_at if onboarding else None,
    )
