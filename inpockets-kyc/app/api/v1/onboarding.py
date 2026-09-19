import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db_session
from app.models.identity_verification import IdentityVerification
from app.models.kyc_record import KYCRecord
from app.models.pan_verification import PANVerification
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.repositories.identity_verification import IdentityVerificationRepository
from app.repositories.kyc_document import KYCDocumentRepository
from app.repositories.kyc_record import KYCRecordRepository
from app.repositories.pan_verification import PANVerificationRepository
from app.schemas.onboarding import (
    IdentityVerificationInitiateResponse,
    IdentityVerificationResponse,
    KYCInitiateResponse,
    KYCStatusResponse,
    OnboardingStatusResponse,
    PANVerificationResponse,
    SubmitCaptureRequest,
    SubmitPANRequest,
)
from app.services.identity_verification import IdentityVerificationService
from app.services.kyc import KYCService
from app.services.pan_verification import PANVerificationService

router = APIRouter()


@router.post("/pan", response_model=PANVerificationResponse)
async def submit_pan(
    request: SubmitPANRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PANVerificationResponse:
    repository = PANVerificationRepository(session)
    service = PANVerificationService(repository)

    record = await service.verify(
        user_id=current_user.id,
        pan_number=request.pan_number,
        full_name=request.full_name,
    )

    await session.commit()

    return PANVerificationResponse(
        id=str(record.id),
        status=record.status,
        verified_name=record.verified_name,
        name_match_result=record.name_match_result,
        failure_reason=record.failure_reason,
    )


@router.get("/pan/latest", response_model=PANVerificationResponse)
async def get_latest_pan_verification(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PANVerificationResponse:
    repository = PANVerificationRepository(session)
    record = await repository.get_latest_for_user(user_id=current_user.id)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No PAN verification found",
        )

    return PANVerificationResponse(
        id=str(record.id),
        status=record.status,
        verified_name=record.verified_name,
        name_match_result=record.name_match_result,
        failure_reason=record.failure_reason,
    )


@router.post("/kyc/initiate", response_model=KYCInitiateResponse)
async def initiate_kyc(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> KYCInitiateResponse:
    repository = KYCRecordRepository(session)
    kyc_document_repository = KYCDocumentRepository(session)
    document_repository = DocumentRepository(session)
    service = KYCService(repository, kyc_document_repository, document_repository)

    record, consent_url = await service.initiate(user_id=current_user.id)

    await session.commit()

    return KYCInitiateResponse(
        id=str(record.id),
        status=record.status,
        consent_url=consent_url,
    )


@router.get("/kyc/{kyc_record_id}", response_model=KYCStatusResponse)
async def get_kyc_status(
    kyc_record_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> KYCStatusResponse:
    repository = KYCRecordRepository(session)
    record = await repository.get_by_id(kyc_record_id=kyc_record_id)

    if record is None or record.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC record not found",
        )

    kyc_document_repository = KYCDocumentRepository(session)
    document_repository = DocumentRepository(session)
    service = KYCService(repository, kyc_document_repository, document_repository)

    record = await service.refresh_status(record=record)

    await session.commit()

    document_count = await kyc_document_repository.count_for_kyc_record(
        kyc_record_id=record.id,
    )

    return KYCStatusResponse(
        id=str(record.id),
        status=record.status,
        completed_at=record.completed_at,
        document_count=document_count,
        failure_reason=record.failure_reason,
    )


@router.post(
    "/identity-verification/initiate",
    response_model=IdentityVerificationInitiateResponse,
)
async def initiate_identity_verification(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> IdentityVerificationInitiateResponse:
    repository = IdentityVerificationRepository(session)
    service = IdentityVerificationService(repository)

    record, capture_session_token = await service.start_session(
        user_id=current_user.id,
    )

    await session.commit()

    return IdentityVerificationInitiateResponse(
        id=str(record.id),
        status=record.status,
        capture_session_token=capture_session_token,
    )


@router.post(
    "/identity-verification/{record_id}/submit",
    response_model=IdentityVerificationResponse,
)
async def submit_identity_verification_capture(
    record_id: uuid.UUID,
    request: SubmitCaptureRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> IdentityVerificationResponse:
    repository = IdentityVerificationRepository(session)
    record = await repository.get_by_id(record_id=record_id)

    if record is None or record.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity verification not found",
        )

    service = IdentityVerificationService(repository)

    record = await service.submit_capture(
        record=record,
        capture_ref=request.capture_ref,
    )

    await session.commit()

    return IdentityVerificationResponse(
        id=str(record.id),
        status=record.status,
        confidence_score=record.confidence_score,
        failure_reason=record.failure_reason,
    )


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> OnboardingStatusResponse:
    pan_result = await session.execute(
        select(PANVerification)
        .where(PANVerification.user_id == current_user.id)
        .order_by(PANVerification.created_at.desc())
        .limit(1)
    )
    pan_record = pan_result.scalar_one_or_none()

    kyc_result = await session.execute(
        select(KYCRecord)
        .where(KYCRecord.user_id == current_user.id)
        .order_by(KYCRecord.created_at.desc())
        .limit(1)
    )
    kyc_record = kyc_result.scalar_one_or_none()

    identity_result = await session.execute(
        select(IdentityVerification)
        .where(IdentityVerification.user_id == current_user.id)
        .order_by(IdentityVerification.created_at.desc())
        .limit(1)
    )
    identity_record = identity_result.scalar_one_or_none()

    pan_status = pan_record.status if pan_record else None
    kyc_status = kyc_record.status if kyc_record else None
    identity_status = identity_record.status if identity_record else None

    onboarding_complete = (
        pan_status == "verified"
        and kyc_status == "verified"
        and identity_status == "verified"
    )

    return OnboardingStatusResponse(
        mobile_verified=True,
        pan_status=pan_status,
        kyc_status=kyc_status,
        identity_verification_status=identity_status,
        onboarding_complete=onboarding_complete,
    )
