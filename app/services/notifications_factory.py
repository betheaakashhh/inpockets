from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.providers.factory import get_notification_provider
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.notification import NotificationRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService
from app.services.notifications import NotificationService


def build_notification_service(session: AsyncSession) -> NotificationService:
    admin_users = AdminUserRepository(session)
    return NotificationService(
        session=session,
        repository=NotificationRepository(session),
        admin_user_repository=admin_users,
        admin_authorization_service=AdminAuthorizationService(admin_user_repository=admin_users),
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session), admin_user_repository=admin_users
        ),
        provider=get_notification_provider(),
        settings=get_settings(),
    )
