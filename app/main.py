import asyncio
import logging
import sys
from fastapi.middleware.cors import CORSMiddleware
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# Paths whose request bodies contain sensitive data. FastAPI's default 422
# body echoes the rejected input back; for these routes it must not.
_SENSITIVE_INPUT_PREFIXES = ("/api/v1/bank-verifications",)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    if request.url.path.startswith(_SENSITIVE_INPUT_PREFIXES):
        safe = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)

    logger.exception(
        "Unhandled exception: path=%s, request_id=%s",
        request.url.path,
        request_id,
        exc_info=exc,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            }
        },
    )


app.include_router(
    api_router,
    prefix="/api/v1",
)
