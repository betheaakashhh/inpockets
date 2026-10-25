from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.services.audit_log import AuditLogService
from app.services.late_charges import LateChargeService


def build_late_charge_service(session: AsyncSession) -> LateChargeService:
    return LateChargeService(
        session=session,
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=AdminUserRepository(session),
        ),
    )
