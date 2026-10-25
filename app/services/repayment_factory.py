from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.factory import get_payment_provider
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.disbursement import DisbursementRepository
from app.repositories.loan_offer import LoanOfferRepository
from app.repositories.repayment import RepaymentRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.ledger_factory import build_ledger_service
from app.services.repayment import RepaymentService


def build_repayment_service(session: AsyncSession) -> RepaymentService:
    admin_users = AdminUserRepository(session)
    return RepaymentService(
        session=session,
        repository=RepaymentRepository(session),
        offer_repository=LoanOfferRepository(session),
        disbursement_repository=DisbursementRepository(session),
        ledger_service=build_ledger_service(session),
        admin_user_repository=admin_users,
        provider=get_payment_provider(),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=admin_users,
        ),
        admin_authorization_service=AdminAuthorizationService(admin_user_repository=admin_users),
        settings=get_settings(),
    )
