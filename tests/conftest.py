import asyncio
import selectors

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import delete
from uuid import uuid4
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.otp_verification import OTPVerification
from app.models.user import User
from app.models.document import Document
from app.models.kyc_document import KYCDocument
from app.models.kyc_record import KYCRecord
from app.models.pan_verification import PANVerification
from app.models.identity_verification import IdentityVerification
from app.models.user_session import UserSession
from app.models.admin_user import AdminUser


settings = get_settings()


@pytest.fixture(scope="session")
def event_loop_policy():
    class SelectorEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self):
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    return SelectorEventLoopPolicy()


@pytest_asyncio.fixture(autouse=True)
async def clean_database() -> None:
    async for session in get_db_session():
        await session.execute(delete(KYCDocument))
        await session.execute(delete(PANVerification))
        await session.execute(delete(IdentityVerification))
        await session.execute(delete(KYCRecord))
        await session.execute(delete(Document))
        await session.execute(delete(UserSession))
        await session.execute(delete(OTPVerification))
        await session.execute(delete(AdminUser))
        await session.execute(delete(User))
        await session.commit()
        break

@pytest_asyncio.fixture
async def db_session():
    async for session in get_db_session():
        yield session
        break

@pytest_asyncio.fixture(autouse=True)
async def clean_redis() -> None:
    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        keys = []

        async for key in redis_client.scan_iter(match="otp:request:*"):
            keys.append(key)

        if keys:
            await redis_client.delete(*keys)
    finally:
        await redis_client.aclose()

@pytest_asyncio.fixture
async def user(db_session):
    user = User(
        phone_number=f"9{uuid4().int % 1_000_000_000:09d}",
    )
    db_session.add(user)
    await db_session.flush()
    return user

@pytest_asyncio.fixture
async def admin_user(db_session, user):
    admin = AdminUser(
        user_id=user.id,
        role="UNDERWRITER",
        is_active=True,
    )
    db_session.add(admin)
    await db_session.flush()
    return admin