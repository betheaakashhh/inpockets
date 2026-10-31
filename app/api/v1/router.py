from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.pan_verification import router as pan_verification_router
from app.api.v1.kyc import router as kyc_router
from app.api.v1.identity_verification import router as identity_verification_router
from app.api.v1.admin_customers import router as admin_customers_router
from app.api.v1.documents import router as documents_router
from app.api.v1.loan_application import router as loan_application_router
from app.api.v1.admin_loan_application import (
    router as admin_loan_application_router,
)
from app.api.v1.loan_offer import router as loan_offer_router
from app.api.v1.admin_loan_offer import router as admin_loan_offer_router

from app.api.v1.esign import router as esign_router
from app.api.v1.admin_esign import router as admin_esign_router
from app.api.v1.webhooks_esign import router as webhooks_esign_router

from app.api.v1.bank_verification import router as bank_verification_router
from app.api.v1.admin_bank_verification import router as admin_bank_verification_router

from app.api.v1.disbursement import router as disbursement_router
from app.api.v1.admin_disbursement import router as admin_disbursement_router
from app.api.v1.webhooks_disbursement import router as webhooks_disbursement_router

from app.api.v1.repayment import router as repayment_router
from app.api.v1.admin_repayment import router as admin_repayment_router
from app.api.v1.webhooks_payment import router as webhooks_payment_router
from app.api.v1.admin_ledger import router as admin_ledger_router
from app.api.v1.admin_pricing import router as admin_pricing_router
from app.api.v1.admin_reconciliation import router as admin_reconciliation_router
from app.api.v1.admin_collections import router as admin_collections_router

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
api_router.include_router(
    loan_application_router,
    prefix="/loan-applications",
    tags=["Loan Applications"],
)
api_router.include_router(
    admin_loan_application_router,
    prefix="/admin/loan-applications",
    tags=["Admin Loan Applications"],
)

api_router.include_router(
    loan_offer_router,
    prefix="/loan-offers",
    tags=["Loan Offers"],
)

api_router.include_router(
    admin_loan_offer_router,
    prefix="/admin/loan-offers",
    tags=["Admin Loan Offers"],
)

api_router.include_router(
    esign_router,
    prefix="/loan-offers",
    tags=["E-Sign"],
)

api_router.include_router(
    admin_esign_router,
    prefix="/admin/loan-offers",
    tags=["Admin E-Sign"],
)

api_router.include_router(
    webhooks_esign_router,
    prefix="/webhooks",
    tags=["Webhooks"],
)

api_router.include_router(
    bank_verification_router,
    prefix="/bank-verifications",
    tags=["Bank Verification"],
)

api_router.include_router(
    admin_bank_verification_router,
    prefix="/admin/bank-verifications",
    tags=["Admin Bank Verification"],
)

api_router.include_router(
    disbursement_router,
    prefix="/loan-offers",
    tags=["Disbursement"],
)

api_router.include_router(
    admin_disbursement_router,
    prefix="/admin/disbursements",
    tags=["Admin Disbursement"],
)

api_router.include_router(
    webhooks_disbursement_router,
    prefix="/webhooks",
    tags=["Webhooks"],
)

api_router.include_router(
    repayment_router,
    prefix="/loan-offers",
    tags=["Repayment"],
)

api_router.include_router(
    admin_repayment_router,
    prefix="/admin/repayments",
    tags=["Admin Repayment"],
)

api_router.include_router(
    webhooks_payment_router,
    prefix="/webhooks",
    tags=["Webhooks"],
)

api_router.include_router(
    admin_ledger_router,
    prefix="/admin/ledger",
    tags=["Admin Ledger"],
)

api_router.include_router(
    admin_pricing_router,
    prefix="/admin/pricing",
    tags=["Admin Pricing"],
)

api_router.include_router(
    admin_reconciliation_router,
    prefix="/admin/reconciliation",
    tags=["Admin Reconciliation"],
)

api_router.include_router(
    admin_collections_router,
    prefix="/admin/collections",
    tags=["Admin Collections"],
)
