from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.pan_verification import router as pan_verification_router
from app.api.v1.kyc import router as kyc_router
from app.api.v1.identity_verification import router as identity_verification_router
from app.api.v1.admin_customers import router as admin_customers_router
from app.api.v1.documents import router as documents_router

api_router = APIRouter()

api_router.include_router(
    health_router,
    prefix="/health",
    tags=["Health"],
)

api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["Authentication"],
)

api_router.include_router(
    onboarding_router,
    prefix="/onboarding",
    tags=["Onboarding"],
)

api_router.include_router(
    pan_verification_router,
    prefix="/onboarding",
    tags=["KYC - PAN"],
)

api_router.include_router(
    kyc_router,
    prefix="/onboarding",
    tags=["KYC"],
)

api_router.include_router(
    identity_verification_router,
    prefix="/onboarding",
    tags=["KYC - Identity Verification"],
)

api_router.include_router(
    admin_customers_router,
    prefix="/admin/customers",
    tags=["Admin - Customers"],
)

api_router.include_router(
    documents_router,
    prefix="/documents",
    tags=["Documents"],
)