from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.factory import get_disbursement_provider
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.bank_verification import BankVerificationRepository
from app.repositories.disbursement import DisbursementRepository
from app.repositories.esign import ESignRepository
from app.repositories.loan_offer import LoanOfferRepository
from app.repositories.user_profile import UserProfileRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.bank_verification_factory import build_bank_verification_service
from app.services.disbursement import DisbursementService
from app.services.ledger_factory import build_ledger_service


def build_disbursement_service(session: AsyncSession) -> DisbursementService:
    admin_users = AdminUserRepository(session)
    return DisbursementService(
        session=session,
        repository=DisbursementRepository(session),
        offer_repository=LoanOfferRepository(session),
        esign_repository=ESignRepository(session),
        bank_repository=BankVerificationRepository(session),
        bank_service=build_bank_verification_service(session),
        profile_repository=UserProfileRepository(session),
        admin_user_repository=admin_users,
        ledger_service=build_ledger_service(session),
        provider=get_disbursement_provider(),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=admin_users,
        ),
        admin_authorization_service=AdminAuthorizationService(
            admin_user_repository=admin_users,
        ),
        settings=get_settings(),
    )
