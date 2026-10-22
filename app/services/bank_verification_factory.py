from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.encryption import get_field_encryptor
from app.providers.factory import get_bank_verification_provider
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.bank_verification import BankVerificationRepository
from app.repositories.user_profile import UserProfileRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.bank_verification import BankVerificationService


def build_bank_verification_service(session: AsyncSession) -> BankVerificationService:
    admin_users = AdminUserRepository(session)
    settings = get_settings()
    return BankVerificationService(
        session=session,
        repository=BankVerificationRepository(session),
        profile_repository=UserProfileRepository(session),
        admin_user_repository=admin_users,
        provider=get_bank_verification_provider(),
        encryptor_factory=lambda: get_field_encryptor(settings),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=admin_users,
        ),
        admin_authorization_service=AdminAuthorizationService(
            admin_user_repository=admin_users,
        ),
        settings=settings,
    )
