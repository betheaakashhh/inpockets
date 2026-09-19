import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware

configure_logging()

logger = logging.getLogger(__name__)

settings = get_settings()



app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend API for the InPockets digital lending platform.",
)
#middleware 
app.add_middleware(RequestIDMiddleware)

@app.exception_handler(AppException)
async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)

    logger.warning(
        "Application error: code=%s, message=%s, status_code=%d, path=%s, request_id=%s",
        exc.code,
        exc.message,
        exc.status_code,
        request.url.path,
        request_id,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


app.include_router(
    api_router,
    prefix="/api/v1",
)