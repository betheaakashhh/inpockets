from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        actor_admin_user_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: str,
        request_id: str | None = None,
        ip_address: str | None = None,
        reason: str | None = None,
        event_metadata: dict | None = None,
    ) -> AuditLog:
        log = AuditLog(
            actor_admin_user_id=actor_admin_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id,
            ip_address=ip_address,
            reason=reason,
            event_metadata=event_metadata,
        )
        self.session.add(log)
        await self.session.flush()
        return log
