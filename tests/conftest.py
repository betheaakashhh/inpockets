import asyncio
import sys

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.otp_verification import OTPVerification
from app.models.user import User
from app.models.user_session import UserSession


if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )

settings = get_settings()


@pytest.fixture(autouse=True)
def clean_database() -> None:
    async def cleanup() -> None:
        async for session in get_db_session():
            await session.execute(delete(UserSession))
            await session.execute(delete(OTPVerification))
            await session.execute(delete(User))
            await session.commit()
            break

    asyncio.run(cleanup())


@pytest.fixture(autouse=True)
def clean_redis() -> None:
    async def cleanup() -> None:
        redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

        try:
            keys = []

            async for key in redis_client.scan_iter(
                match="otp:request:*"
            ):
                keys.append(key)

            if keys:
                await redis_client.delete(*keys)
        finally:
            await redis_client.aclose()

    asyncio.run(cleanup())