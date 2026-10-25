from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.pricing import PricingRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.pricing import PricingService


def build_pricing_service(session: AsyncSession) -> PricingService:
    admin_users = AdminUserRepository(session)
    return PricingService(
        repository=PricingRepository(session),
        admin_user_repository=admin_users,
        admin_authorization_service=AdminAuthorizationService(admin_user_repository=admin_users),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=admin_users,
        ),
        settings=get_settings(),
    )
