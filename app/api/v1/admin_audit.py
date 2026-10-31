from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain.admin import AdminPermission, AdminRole, require_permission
from app.models.admin_user import AdminUser
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.schemas.audit import AuditLogPage, AuditLogResponse
from app.services.audit_log import AuditLogService

router = APIRouter(
    dependencies=[Depends(limit_user("admin-audit", sensitive=True))]
)


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    request: Request,
    action: str | None = None,
    entity_type: str | None = None,
    actor_role: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(get_current_admin),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    require_permission(AdminRole(admin.role), AdminPermission.AUDIT_READ)
    rows = await AuditLogRepository(session).list(
        action=action,
        entity_type=entity_type,
        actor_role=actor_role,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    await AuditLogService(
        audit_log_repository=AuditLogRepository(session),
        admin_user_repository=AdminUserRepository(session),
    ).record_admin_action(
        actor_user_id=admin.user_id,
        action="AUDIT_LOGS_VIEWED",
        entity_type="audit_log",
        entity_id="collection",
        request_id=getattr(request.state, "request_id", None) if request else None,
        ip_address=client_ip(request) if request else None,
        event_metadata={"limit": limit, "offset": offset},
    )
    await session.commit()
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(row) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )
