from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.document import DocumentRepository
from app.repositories.loan_application import LoanApplicationRepository
from app.repositories.loan_decision import LoanDecisionRepository
from app.repositories.loan_offer import LoanOfferRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.document import DocumentService
from app.services.loan_offer import LoanOfferService
from app.services.loan_offer_issuance import LoanOfferIssuanceService


def build_loan_offer_service(session: AsyncSession) -> LoanOfferService:
    admin_users = AdminUserRepository(session)
    return LoanOfferService(
        session=session,
        offer_repository=LoanOfferRepository(session),
        application_repository=LoanApplicationRepository(session),
        document_repository=DocumentRepository(session),
        admin_authorization_service=AdminAuthorizationService(
            admin_user_repository=admin_users,
        ),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=admin_users,
        ),
        decision_repository=LoanDecisionRepository(session),
    )


def build_loan_offer_issuance_service(
    session: AsyncSession,
) -> LoanOfferIssuanceService:
    return LoanOfferIssuanceService(
        offer_service=build_loan_offer_service(session),
        document_service=DocumentService(session),
        offer_repository=LoanOfferRepository(session),
        application_repository=LoanApplicationRepository(session),
    )
