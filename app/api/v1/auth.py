import ipaddress
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    get_current_user,
    get_current_user_session,
)
from app.db.session import get_db_session
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.otp_verification import OTPVerificationRepository
from app.repositories.user import UserRepository
from app.repositories.user_session import UserSessionRepository
from app.schemas.auth import (
    RefreshTokenRequest,
    RequestOTPRequest,
    VerifyOTPRequest,
)
from app.services.otp import (
    OTPAlreadyVerifiedError,
    OTPAttemptsExceededError,
    OTPExpiredError,
    OTPInvalidError,
    OTPRateLimitError,
    OTPService,
    OTPServiceUnavailableError,
    OTPCooldownError,
    OTPSMSDeliveryError,
)
from app.services.session import SessionService, hash_token


security = HTTPBearer()
router = APIRouter()


def _client_ip(http_request: Request) -> str | None:
    if http_request.client is None:
        return None

    try:
        ipaddress.ip_address(http_request.client.host)
        return http_request.client.host
    except ValueError:
        return None


@router.post("/request-otp", status_code=status.HTTP_200_OK)
async def request_otp(
    request: RequestOTPRequest,
    session: AsyncSession = Depends(get_db_session),
):
    repository = OTPVerificationRepository(session)
    service = OTPService(repository)

    try:
        await service.create_otp(
            phone_number=request.phone_number,
            purpose="login",
        )
    except OTPCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except OTPRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except OTPServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except OTPSMSDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    await session.commit()

    return {
        "message": "OTP sent successfully",
    }


@router.post("/verify-otp", status_code=status.HTTP_200_OK)
async def verify_otp(
    request: VerifyOTPRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    otp_repository = OTPVerificationRepository(session)
    otp_service = OTPService(otp_repository)

    try:
        await otp_service.check_verify_rate_limit(
            phone_number=request.phone_number,
            client_ip=_client_ip(http_request),
        )
    except OTPRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP verification attempts. Please try again later.",
        ) from exc
    except OTPServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    otp_record = await otp_repository.get_latest(
        phone_number=request.phone_number,
        purpose="login",
    )

    if otp_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP",
        )

    try:
        await otp_service.verify_otp(
            record=otp_record,
            otp=request.otp,
        )
    except OTPInvalidError:
        await session.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP",
        ) from None
    except (
        OTPExpiredError,
        OTPAlreadyVerifiedError,
        OTPAttemptsExceededError,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP",
        ) from None

    user_repository = UserRepository(session)

    user = await user_repository.get_by_phone_number(
        request.phone_number
    )

    if user is None:
        user = await user_repository.create(
            phone_number=request.phone_number,
        )

    otp_record.user_id = user.id
    await otp_repository.update(otp_record)

    client_ip = _client_ip(http_request)

    session_repository = UserSessionRepository(session)
    session_service = SessionService(session_repository)

    user_session, access_token, refresh_token = (
        await session_service.create_session(
            user_id=user.id,
            device_name=request.device_name,
            device_type=request.device_type,
            ip_address=client_ip,
            user_agent=http_request.headers.get("user-agent"),
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


@router.get("/sessions")
async def get_sessions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    session_repository = UserSessionRepository(session)

    sessions = await session_repository.get_by_user_id(
        current_user.id,
    )

    return {
        "sessions": [
            {
                "id": str(user_session.id),
                "device_name": user_session.device_name,
                "device_type": user_session.device_type,
                "ip_address": (
                    str(user_session.ip_address)
                    if user_session.ip_address is not None
                    else None
                ),
                "user_agent": user_session.user_agent,
                "created_at": user_session.created_at,
                "last_used_at": user_session.last_used_at,
                "revoked_at": user_session.revoked_at,
            }
            for user_session in sessions
        ],
    }


@router.delete("/sessions/others")
async def revoke_other_sessions(
    current_user_and_session: tuple[User, UserSession] = Depends(
        get_current_user_session
    ),
    session: AsyncSession = Depends(get_db_session),
):
    current_user, current_session = current_user_and_session

    session_repository = UserSessionRepository(session)

    sessions = await session_repository.get_by_user_id(
        current_user.id,
    )

    revoked_count = 0

    for user_session in sessions:
        if (
            user_session.id != current_session.id
            and user_session.revoked_at is None
        ):
            await session_repository.revoke(
                user_session,
                reason="logout_other_sessions",
            )
            revoked_count += 1

    await session.commit()

    return {
        "message": "Other sessions revoked successfully",
        "revoked_count": revoked_count,
    }


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    session_repository = UserSessionRepository(session)

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from None

    user_session = await session_repository.get_by_id(
        session_uuid,
    )

    if (
        user_session is None
        or user_session.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    await session_repository.revoke(
        user_session,
        reason="manual_revoke",
    )

    await session.commit()

    return {
        "message": "Session revoked successfully",
    }


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
    session: AsyncSession = Depends(get_db_session),
):
    session_repository = UserSessionRepository(session)

    refresh_token_hash = hash_token(request.refresh_token)

    # Serialize refresh-token rotation at the database row level.
    user_session = await session_repository.get_by_refresh_token_hash_for_update(
        refresh_token_hash
    )

    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if user_session.revoked_at is not None:
        if user_session.revocation_reason == "rotated":
            await session_repository.revoke_token_family(
                user_session.token_family_id,
                reason="reuse_detected",
            )

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected",
            )

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
