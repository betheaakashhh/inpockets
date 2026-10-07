from __future__ import annotations

from uuid import UUID

from app.domain.admin import AdminRole
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository


class AuditLogService:
    """Centralized service for immutable audit records."""

    def __init__(
        self,
        *,
        audit_log_repository: AuditLogRepository,
        admin_user_repository: AdminUserRepository,
    ):
        self.audit_log_repository = audit_log_repository
        self.admin_user_repository = admin_user_repository

    async def record_admin_action(
        self,
        *,
        actor_user_id: UUID,
        action: str,
        entity_type: str,
        entity_id: str,
        request_id: str | None = None,
        ip_address: str | None = None,
        reason: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        event_metadata: dict | None = None,
    ):
        admin_user = await self.admin_user_repository.get_by_user_id(
            actor_user_id
        )

        if admin_user is None:
            raise PermissionError("user is not an admin")

        if not admin_user.is_active:
            raise PermissionError("admin user is inactive")

        try:
            actor_role = AdminRole(admin_user.role)
        except ValueError as exc:
            raise PermissionError("admin user has an invalid role") from exc

        return await self.audit_log_repository.create(
            actor_admin_user_id=admin_user.id,
            actor_role=actor_role.value,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id,
            ip_address=ip_address,
            reason=reason,
            old_value=old_value,
            new_value=new_value,
            event_metadata=event_metadata,
        )