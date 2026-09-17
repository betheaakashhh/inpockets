import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.user_session import UserSession
from app.repositories.user_session import UserSessionRepository


ACCESS_TOKEN_BYTES = 32
REFRESH_TOKEN_BYTES = 32

ACCESS_TOKEN_EXPIRY_MINUTES = 15
REFRESH_TOKEN_EXPIRY_DAYS = 30


def generate_access_token() -> str:
    return secrets.token_urlsafe(ACCESS_TOKEN_BYTES)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_token_hash(
    token: str,
    token_hash: str,
) -> bool:
    expected_hash = hash_token(token)

    return hmac.compare_digest(
        expected_hash,
        token_hash,
    )


class SessionService:
    def __init__(
        self,
        repository: UserSessionRepository,
    ):
        self.repository = repository

    async def create_session(
        self,
        *,
        user_id,
        device_name: str | None = None,
        device_type: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[UserSession, str, str]:
        access_token = generate_access_token()
        refresh_token = generate_refresh_token()

        access_token_hash = hash_token(access_token)
        refresh_token_hash = hash_token(refresh_token)

        now = datetime.now(timezone.utc)

        access_token_expires_at = (
            now
            + timedelta(minutes=ACCESS_TOKEN_EXPIRY_MINUTES)
        )

        refresh_token_expires_at = (
            now
            + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)
        )

        token_family_id = uuid.uuid4()

        user_session = await self.repository.create(
            user_id=user_id,
            token_family_id=token_family_id,
            access_token_hash=access_token_hash,
            refresh_token_hash=refresh_token_hash,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
            device_name=device_name,
            device_type=device_type,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return (
            user_session,
            access_token,
            refresh_token,
        )

    async def refresh_session(
        self,
        user_session: UserSession,
    ) -> tuple[UserSession, str, str]:
        # The current session is the token that was just used.
        # Mark it as rotated so reuse can be detected later.
        await self.repository.revoke(
            user_session,
            reason="rotated",
        )

        access_token = generate_access_token()
        refresh_token = generate_refresh_token()

        access_token_hash = hash_token(access_token)
        refresh_token_hash = hash_token(refresh_token)

        now = datetime.now(timezone.utc)

        access_token_expires_at = (
            now
            + timedelta(minutes=ACCESS_TOKEN_EXPIRY_MINUTES)
        )

        refresh_token_expires_at = (
            now
            + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)
        )

        new_session = await self.repository.create(
            user_id=user_session.user_id,
            token_family_id=user_session.token_family_id,
            access_token_hash=access_token_hash,
            refresh_token_hash=refresh_token_hash,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
            device_name=user_session.device_name,
            device_type=user_session.device_type,
            ip_address=user_session.ip_address,
            user_agent=user_session.user_agent,
        )

        return (
            new_session,
            access_token,
            refresh_token,
        )

    async def get_user_sessions(
        self,
        *,
        user_id: uuid.UUID,
    ) -> list[UserSession]:
        return await self.repository.get_by_user_id(user_id)
   
    async def revoke_user_session(
     self,
     *,
     user_id: uuid.UUID,
     session_id: uuid.UUID,
    ) -> UserSession | None:
        user_session = await self.repository.get_by_id(session_id)

        if user_session is None:
            return None

        # Never allow one user to revoke another user's session.
        if user_session.user_id != user_id:
            return None

        if user_session.revoked_at is None:
            await self.repository.revoke(
                user_session,
                reason="user_revoked",
            )

        return user_session
    
    async def revoke_other_sessions(
        self,
        *,
        user_id: uuid.UUID,
        current_session_id: uuid.UUID,
    ) -> None:
        sessions = await self.repository.get_by_user_id(user_id)

        for user_session in sessions:
            if user_session.id == current_session_id:
                continue
            if user_session.revoked_at is None:
                await self.repository.revoke(
                    user_session,
                    reason="user_revoked",
                )
            
                