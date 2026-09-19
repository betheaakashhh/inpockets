import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal


@pytest.mark.asyncio
async def test_database_connection():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))

        assert result.scalar() == 1