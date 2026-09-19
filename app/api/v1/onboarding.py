from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.onboarding import (
    ConsentRequest,
    OnboardingResponse,
    OnboardingStepUpdateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.services.onboarding import OnboardingService


router = APIRouter()


def get_onboarding_service(
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingService:
    return OnboardingService(session)


@router.get("", response_model=OnboardingResponse)
async def get_onboarding(
    current_user: User = Depends(get_current_user),
    service: OnboardingService = Depends(get_onboarding_service),
) -> OnboardingResponse:
    onboarding = await service.get_or_create_onboarding(
        user_id=current_user.id,
    )

    await service.session.commit()
    await service.session.refresh(onboarding)

    return OnboardingResponse.model_validate(onboarding)


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    service: OnboardingService = Depends(get_onboarding_service),
) -> ProfileResponse:
    profile = await service.get_or_create_profile(
        user_id=current_user.id,
    )

    await service.session.commit()
    await service.session.refresh(profile)

    return ProfileResponse.model_validate(profile)


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: OnboardingService = Depends(get_onboarding_service),
) -> ProfileResponse:
    profile = await service.update_profile(
        user_id=current_user.id,
        first_name=request.first_name,
        last_name=request.last_name,
        date_of_birth=request.date_of_birth,
        gender=request.gender,
    )

    await service.session.commit()
    await service.session.refresh(profile)

    return ProfileResponse.model_validate(profile)


@router.post("/consents", status_code=status.HTTP_201_CREATED)
async def record_consent(
    request: ConsentRequest,
    current_user: User = Depends(get_current_user),
    service: OnboardingService = Depends(get_onboarding_service),
):
    consent = await service.record_consent(
        user_id=current_user.id,
        consent_type=request.consent_type,
        version=request.version,
        status=request.status,
    )

    await service.session.commit()

    return {
        "id": str(consent.id),
        "consent_type": consent.consent_type,
        "version": consent.version,
        "status": consent.status,
        "consented_at": consent.consented_at,
        "created_at": consent.created_at,
    }


@router.patch("", response_model=OnboardingResponse)
async def update_onboarding_step(
    request: OnboardingStepUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: OnboardingService = Depends(get_onboarding_service),
) -> OnboardingResponse:
    try:
        onboarding = await service.update_onboarding_step(
            user_id=current_user.id,
            current_step=request.current_step,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await service.session.commit()
    await service.session.refresh(onboarding)

    return OnboardingResponse.model_validate(onboarding)