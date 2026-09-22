from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.identity_verification import (
    IdentityVerificationCaptureRequest,
    IdentityVerificationResponse,
)
from app.services.identity_verification import IdentityVerificationService


router = APIRouter()


def get_identity_verification_service(
    session: AsyncSession = Depends(get_db_session),
) -> IdentityVerificationService:
    return IdentityVerificationService(session)


@router.post(
    "/identity-verification",
    response_model=IdentityVerificationResponse,
)
async def start_identity_verification(
    current_user: User = Depends(get_current_user),
    service: IdentityVerificationService = Depends(get_identity_verification_service),
) -> IdentityVerificationResponse:
    record, capture_session_token = await service.start(user_id=current_user.id)

    await service.session.commit()
    await service.session.refresh(record)

    return IdentityVerificationResponse(
        **IdentityVerificationResponse.model_validate(record).model_dump(),
        capture_session_token=capture_session_token,
    )


@router.post(
    "/identity-verification/capture",
    response_model=IdentityVerificationResponse,
)
async def submit_identity_capture(
    payload: IdentityVerificationCaptureRequest,
    current_user: User = Depends(get_current_user),
    service: IdentityVerificationService = Depends(get_identity_verification_service),
) -> IdentityVerificationResponse:
    record = await service.submit_capture(
        user_id=current_user.id,
        capture_ref=payload.capture_ref,
    )

    await service.session.commit()
    await service.session.refresh(record)

    return IdentityVerificationResponse.model_validate(record)


@router.get(
    "/identity-verification",
    response_model=IdentityVerificationResponse | None,
)
async def get_identity_verification(
    current_user: User = Depends(get_current_user),
    service: IdentityVerificationService = Depends(get_identity_verification_service),
) -> IdentityVerificationResponse | None:
    record = await service.get_status(user_id=current_user.id)
    if record is None:
        return None

    return IdentityVerificationResponse.model_validate(record)
