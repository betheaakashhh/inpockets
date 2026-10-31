from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.repositories.admin_user import AdminUserRepository
from app.repositories.audit_log import AuditLogRepository
from app.schemas.reporting import ReportResponse, ReportType
from app.services.audit_log import AuditLogService
from app.services.reporting import ReportingService

router = APIRouter(
    dependencies=[Depends(limit_user("admin-reporting", sensitive=True))]
)


@router.get("/{report_type}", response_model=ReportResponse)
async def generate_report(
    report_type: ReportType,
    request: Request,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: AdminUser = Depends(get_current_admin),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
):
    try:
        rows, has_more = await ReportingService(session).generate(
            actor_role=admin.role,
            report_type=report_type,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
    except PermissionError as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Insufficient report permissions"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await AuditLogService(
        audit_log_repository=AuditLogRepository(session),
        admin_user_repository=AdminUserRepository(session),
    ).record_admin_action(
        actor_user_id=admin.user_id,
        action="REPORT_VIEWED",
        entity_type="report",
        entity_id=report_type.value,
        request_id=getattr(request.state, "request_id", None),
        ip_address=client_ip(request),
        event_metadata={"limit": limit, "offset": offset},
    )
    await session.commit()
    return ReportResponse(
        report_type=report_type,
        generated_at=datetime.now(UTC),
        rows=rows,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )
