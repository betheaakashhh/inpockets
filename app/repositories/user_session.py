from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_session import UserSession


class UserSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id,
        access_token_hash: str,
        refresh_token_hash: str,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime,
    ) -> UserSession:
        user_session = UserSession(
            user_id=user_id,
            access_token_hash=access_token_hash,
            refresh_token_hash=refresh_token_hash,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
        )

        self.session.add(user_session)
        await self.session.flush()

        return user_session

    async def get_by_access_token_hash(
        self,
        token_hash: str,
    ) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession).where(
                UserSession.access_token_hash == token_hash
            )
        )

        return result.scalar_one_or_none()

    async def get_by_refresh_token_hash(
        self,
        token_hash: str,
    ) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession).where(
                UserSession.refresh_token_hash == token_hash
            )
        )

        return result.scalar_one_or_none()

    async def rotate_tokens(
        self,
        user_session: UserSession,
        *,
        access_token_hash: str,
        refresh_token_hash: str,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime,
    ) -> UserSession:
        user_session.access_token_hash = access_token_hash
        user_session.refresh_token_hash = refresh_token_hash
        user_session.access_token_expires_at = access_token_expires_at
        user_session.refresh_token_expires_at = refresh_token_expires_at
        user_session.last_used_at = datetime.now(timezone.utc)

        await self.session.flush()

        return user_session

    async def revoke(
        self,
        user_session: UserSession,
    ) -> UserSession:
        user_session.revoked_at = datetime.now(timezone.utc)

        await self.session.flush()

        return user_session