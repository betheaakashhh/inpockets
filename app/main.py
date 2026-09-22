import asyncio
import logging
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)

    logger.warning(
        "HTTP error: status_code=%d, path=%s, request_id=%s",
        exc.status_code,
        request.url.path,
        request_id,
    )

    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed"

    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"http_{exc.status_code}",
                "message": message,
                "request_id": request_id,
            }
        },
    )

    if exc.headers:
        response.headers.update(exc.headers)

    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)

    logger.warning(
        "Request validation error: path=%s, request_id=%s",
        request.url.path,
        request_id,
    )

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "request_validation_error",
                "message": "Request validation failed",
                "request_id": request_id,
            }
        },
    )


app.include_router(
    api_router,
    prefix="/api/v1",
)
