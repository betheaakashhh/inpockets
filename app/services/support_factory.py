from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.support import SupportRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.notifications_factory import build_notification_service
from app.services.support import SupportService


def build_support_service(session: AsyncSession) -> SupportService:
    admin_users = AdminUserRepository(session)
    return SupportService(
        session=session,
        repository=SupportRepository(session),
        admin_user_repository=admin_users,
        admin_authorization_service=AdminAuthorizationService(admin_user_repository=admin_users),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session), admin_user_repository=admin_users
        ),
        notifications=build_notification_service(session),
        settings=get_settings(),
    )
