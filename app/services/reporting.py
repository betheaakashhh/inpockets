from __future__ import annotations

from datetime import datetime, timedelta

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
        role = AdminRole(actor_role)
        require_permission(role, AdminPermission.REPORT_READ)
        required_permission = {
            ReportType.DISBURSEMENTS: AdminPermission.REPORT_FINANCIAL,
            ReportType.EXPOSURE: AdminPermission.REPORT_FINANCIAL,
            ReportType.REPAYMENTS: AdminPermission.REPORT_FINANCIAL,
            ReportType.RECONCILIATION: AdminPermission.REPORT_FINANCIAL,
            ReportType.RISK_FRAUD: AdminPermission.REPORT_RISK,
            ReportType.OVERDUE: AdminPermission.REPORT_COLLECTIONS,
            ReportType.COLLECTIONS: AdminPermission.REPORT_COLLECTIONS,
            ReportType.CLOSURES: AdminPermission.REPORT_COLLECTIONS,
        }.get(report_type)
        if required_permission is not None:
            require_permission(role, required_permission)
        if start_at and end_at and end_at <= start_at:
            raise ValueError("end_at must be later than start_at")
        if start_at and end_at and end_at - start_at > timedelta(days=366):
            raise ValueError("report date range cannot exceed 366 days")
        if report_type == ReportType.EXPOSURE and (start_at or end_at):
            raise ValueError(
                "historical exposure is unsupported; omit date filters for current exposure"
            )
        if report_type == ReportType.OVERDUE and (start_at or end_at):
            raise ValueError(
                "overdue is a current snapshot; use collections for opened/closed periods"
            )
        filters = {
            "start_at": start_at,
            "end_at": end_at,
            "limit": min(limit, 200),
            "offset": offset,
        }
        method = getattr(self.repository, report_type.value)
        rows = await method(**filters)
        return rows[:limit], len(rows) > limit
