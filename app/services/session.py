import hashlib
import hmac
import secrets
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
    ) -> tuple[
        UserSession,
        str,
        str,
    ]:
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

        user_session = await self.repository.create(
            user_id=user_id,
            access_token_hash=access_token_hash,
            refresh_token_hash=refresh_token_hash,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
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

        user_session = await self.repository.rotate_tokens(
            user_session,
            access_token_hash=access_token_hash,
            refresh_token_hash=refresh_token_hash,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
        )

        return user_session, access_token, refresh_token