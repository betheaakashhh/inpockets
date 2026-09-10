from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.health import check_database_connection
from app.db.session import get_db_session

router = APIRouter()


@router.get("")
async def health_check(
   session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    database_ok = await check_database_connection(session)

    if not database_ok:
        return {
            "status": "degraded",
            "database": "unhealthy",
        }

    return {
        "status": "ok",
        "database": "ok",
    }