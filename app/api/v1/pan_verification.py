from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.pan_verification import PANVerificationRequest, PANVerificationResponse
from app.services.pan_verification import PANVerificationService


router = APIRouter()


def get_pan_verification_service(
    session: AsyncSession = Depends(get_db_session),
) -> PANVerificationService:
    return PANVerificationService(session)


@router.post("/pan", response_model=PANVerificationResponse)
async def verify_pan(
    request: PANVerificationRequest,
    current_user: User = Depends(get_current_user),
    service: PANVerificationService = Depends(get_pan_verification_service),
) -> PANVerificationResponse:
    verification = await service.verify(
        user_id=current_user.id,
        pan_number=request.pan_number,
    )

    await service.session.commit()
    await service.session.refresh(verification)

    return PANVerificationResponse.model_validate(verification)


@router.get("/pan", response_model=PANVerificationResponse | None)
async def get_pan_verification(
    current_user: User = Depends(get_current_user),
    service: PANVerificationService = Depends(get_pan_verification_service),
) -> PANVerificationResponse | None:
    verification = await service.pan_repository.get_latest_for_user(
        user_id=current_user.id,
    )
    if verification is None:
        return None

    return PANVerificationResponse.model_validate(verification)
