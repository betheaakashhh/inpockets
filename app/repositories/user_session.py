import uuid
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
        token_family_id,
        access_token_hash: str,
        refresh_token_hash: str,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime,
        device_name: str | None = None,
        device_type: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        user_session = UserSession(
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

    async def get_by_token_family_id(
        self,
        token_family_id: uuid.UUID,
    ) -> list[UserSession]:
        result = await self.session.execute(
            select(UserSession).where(
                UserSession.token_family_id == token_family_id
            )
        )

        return list(result.scalars().all())

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
        *,
        reason: str = "logout",
    ) -> UserSession:
        user_session.revoked_at = datetime.now(timezone.utc)
        user_session.revocation_reason = reason

        await self.session.flush()

        return user_session

    async def revoke_token_family(
        self,
        token_family_id: uuid.UUID,
        *,
        reason: str = "reuse_detected",
    ) -> None:
        sessions = await self.get_by_token_family_id(token_family_id)

        revoked_at = datetime.now(timezone.utc)

        for user_session in sessions:
            if user_session.revoked_at is None:
                user_session.revoked_at = revoked_at
                user_session.revocation_reason = reason

        await self.session.flush()