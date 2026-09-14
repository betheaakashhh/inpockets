from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.otp_verification import OTPVerificationRepository
from app.schemas.auth import RequestOTPRequest, VerifyOTPRequest
from app.services.otp import (
    OTPAlreadyVerifiedError,
    OTPAttemptsExceededError,
    OTPExpiredError,
    OTPInvalidError,
    OTPService,
)
from app.core.auth import security
from app.db.session import get_db_session
from app.repositories.user import UserRepository
from app.repositories.user_session import UserSessionRepository
from app.services.session import SessionService
from app.core.auth import get_current_user
from app.services.session import hash_token, SessionService
from app.schemas.auth import RefreshTokenRequest
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import APIRouter, Depends, HTTPException, status


security = HTTPBearer()

router = APIRouter()


@router.post("/request-otp", status_code=status.HTTP_200_OK)
async def request_otp(
    request: RequestOTPRequest,
    session: AsyncSession = Depends(get_db_session),
):
    repository = OTPVerificationRepository(session)
    service = OTPService(repository)

    _, otp = await service.create_otp(
        phone_number=request.phone_number,
        purpose="login",
    )

    await session.commit()

    return {
        "message": "OTP generated successfully",
        "otp": otp,
    }

#verify otp endpoint
@router.post("/verify-otp", status_code=status.HTTP_200_OK)
async def verify_otp(
    request: VerifyOTPRequest,
    session: AsyncSession = Depends(get_db_session),
):
    otp_repository = OTPVerificationRepository(session)

    otp_record = await otp_repository.get_latest(
        phone_number=request.phone_number,
        purpose="login",
    )

    if otp_record is None:
        return {
            "message": "Invalid or expired OTP",
        }

    otp_service = OTPService(otp_repository)

    try:
        await otp_service.verify_otp(
            record=otp_record,
            otp=request.otp,
        )
    except (
        OTPInvalidError,
        OTPExpiredError,
        OTPAlreadyVerifiedError,
        OTPAttemptsExceededError,
    ):
        return {
            "message": "Invalid or expired OTP",
        }

    # Find existing user
    user_repository = UserRepository(session)

    user = await user_repository.get_by_phone_number(
        request.phone_number
    )

    # Create user for first-time login
    if user is None:
        user = await user_repository.create(
            phone_number=request.phone_number,
        )

    # Link OTP verification to user
    otp_record.user_id = user.id
    await otp_repository.update(otp_record)

    # Create session
    session_repository = UserSessionRepository(session)
    session_service = SessionService(session_repository)

    user_session, access_token, refresh_token = (
        await session_service.create_session(
            user_id=user.id,
        )
    )

    await session.commit()

    return {
    "message": "OTP verified successfully",
    "access_token": access_token,
    "refresh_token": refresh_token,
    "token_type": "bearer",
    "access_token_expires_at": user_session.access_token_expires_at,
    "refresh_token_expires_at": user_session.refresh_token_expires_at,
    "user_id": str(user.id),
}
    
# Get current user endpoint
@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return {
        "id": str(current_user.id),
        "phone_number": current_user.phone_number,
        "status": current_user.status,
    }

@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_db_session),
):
    token = credentials.credentials

    token_hash = hash_token(token)

    session_repository = UserSessionRepository(session)

    user_session = await session_repository.get_by_access_token_hash(
    token_hash
)

    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    await session_repository.revoke(user_session)

    await session.commit()

    return {
        "message": "Logged out successfully",
    }

@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
    session: AsyncSession = Depends(get_db_session),
):
    session_repository = UserSessionRepository(session)

    refresh_token_hash = hash_token(request.refresh_token)

    user_session = await session_repository.get_by_refresh_token_hash(
        refresh_token_hash
    )

    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if user_session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked",
        )

    now = datetime.now(timezone.utc)

    if now >= user_session.refresh_token_expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        )

    session_service = SessionService(session_repository)

    (
        user_session,
        access_token,
        new_refresh_token,
    ) = await session_service.refresh_session(user_session)

    await session.commit()

    return {
        "message": "Token refreshed successfully",
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "access_token_expires_at": user_session.access_token_expires_at,
        "refresh_token_expires_at": user_session.refresh_token_expires_at,
        "user_id": str(user_session.user_id),
    }