from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.kyc import KYCInitiationResponse, KYCStatusResponse
from app.services.kyc import KYCService


router = APIRouter()


def get_kyc_service(session: AsyncSession = Depends(get_db_session)) -> KYCService:
    return KYCService(session)


@router.post("/kyc", response_model=KYCInitiationResponse)
async def initiate_kyc(
    current_user: User = Depends(get_current_user),
    service: KYCService = Depends(get_kyc_service),
) -> KYCInitiationResponse:
    try:
        record, consent_url = await service.initiate(user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await service.session.commit()
    await service.session.refresh(record)
    return KYCInitiationResponse(
        **KYCStatusResponse.model_validate(record).model_dump(),
        consent_url=consent_url,
    )


@router.get("/kyc", response_model=KYCStatusResponse | None)
async def get_kyc_status(
    current_user: User = Depends(get_current_user),
    service: KYCService = Depends(get_kyc_service),
) -> KYCStatusResponse | None:
    record = await service.refresh_status(user_id=current_user.id)
    if record is None:
        return None
    await service.session.commit()
    await service.session.refresh(record)
    return KYCStatusResponse.model_validate(record)
