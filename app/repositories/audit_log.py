from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        actor_admin_user_id: UUID | None,
        actor_role: str | None,
        action: str,
        entity_type: str,
        entity_id: str,
        request_id: str | None = None,
        ip_address: str | None = None,
        reason: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        event_metadata: dict | None = None,
    ) -> AuditLog:
        log = AuditLog(
            actor_admin_user_id=actor_admin_user_id,
            actor_role=actor_role,
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

        self.session.add(log)
        await self.session.flush()

        return log

    async def list(
        self,
        *,
        action: str | None = None,
        entity_type: str | None = None,
        actor_role: str | None = None,
        actor_identifier: UUID | None = None,
        request_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        query: Select[tuple[AuditLog]] = select(AuditLog)
        if action:
            query = query.where(AuditLog.action == action)
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        if actor_role:
            query = query.where(AuditLog.actor_role == actor_role)
        if actor_identifier:
            query = query.where(
                or_(
                    AuditLog.actor_admin_user_id == actor_identifier,
                    AuditLog.event_metadata["actor_user_id"].as_string()
                    == str(actor_identifier),
                )
            )
        if request_id:
            query = query.where(AuditLog.request_id == request_id)
        if start_at:
            query = query.where(AuditLog.created_at >= start_at)
        if end_at:
            query = query.where(AuditLog.created_at < end_at)
        result = await self.session.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        return list(result.all())