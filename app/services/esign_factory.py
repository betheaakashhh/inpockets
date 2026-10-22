from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.factory import get_esign_provider
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.document import DocumentRepository
from app.repositories.esign import ESignRepository
from app.repositories.loan_offer import LoanOfferRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.document import DocumentService
from app.services.esign import ESignService


def build_esign_service(session: AsyncSession) -> ESignService:
    admin_users = AdminUserRepository(session)
    return ESignService(
        session=session,
        repository=ESignRepository(session),
        offer_repository=LoanOfferRepository(session),
        document_repository=DocumentRepository(session),
        document_service=DocumentService(session),
        provider=get_esign_provider(),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=admin_users,
        ),
        admin_authorization_service=AdminAuthorizationService(
            admin_user_repository=admin_users,
        ),
        admin_user_repository=admin_users,
        settings=get_settings(),
    )
