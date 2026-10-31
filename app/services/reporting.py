from __future__ import annotations

from datetime import datetime

from app.domain.admin import AdminPermission, AdminRole, require_permission
from app.repositories.reporting import ReportingRepository
from app.schemas.reporting import ReportType


class ReportingService:
    def __init__(self, session):
        self.repository = ReportingRepository(session)

    async def generate(
        self,
        *,
        actor_role: str,
        report_type: ReportType,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], bool]:
        require_permission(AdminRole(actor_role), AdminPermission.REPORT_READ)
        if start_at and end_at and end_at <= start_at:
            raise ValueError("end_at must be later than start_at")
        if start_at and end_at and (end_at - start_at).days > 366:
            raise ValueError("report date range cannot exceed 366 days")
        filters = {
            "start_at": start_at,
            "end_at": end_at,
            "limit": min(limit, 200),
            "offset": offset,
        }
        method = getattr(self.repository, report_type.value)
        rows = await method(**filters)
        return rows[:limit], len(rows) > limit
