from fastapi import APIRouter
from app.core.exceptions import AppException
router = APIRouter()

#testing error handling
""" @router.get("/test-error")
async def test_error() -> None:
    raise AppException(
        code="TEST_ERROR",
        message="This is a test application error.",
        status_code=400,
    ) """

@router.get("")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}