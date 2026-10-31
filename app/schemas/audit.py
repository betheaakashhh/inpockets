from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.services.audit_log import _safe_snapshot


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_admin_user_id: UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str
    request_id: str | None
    ip_address: str | None
    reason: str | None
    old_value: dict | None
    new_value: dict | None
    event_metadata: dict | None
    created_at: datetime

    @classmethod
    def sanitized_from_orm(cls, row) -> AuditLogResponse:
        payload = {
            key: getattr(row, key)
            for key in (
                "id",
                "actor_admin_user_id",
                "actor_role",
                "action",
                "entity_type",
                "entity_id",
                "request_id",
                "ip_address",
                "reason",
                "created_at",
            )
        }
        payload["old_value"] = _safe_snapshot(
            row.old_value, entity_type=row.entity_type
        )
        payload["new_value"] = _safe_snapshot(
            row.new_value, entity_type=row.entity_type
        )
        payload["event_metadata"] = _safe_snapshot(
            row.event_metadata, entity_type=row.entity_type
        )
        return cls.model_validate(payload)


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    limit: int
    offset: int
    has_more: bool
