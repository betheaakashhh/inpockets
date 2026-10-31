from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    limit: int
    offset: int
    has_more: bool
