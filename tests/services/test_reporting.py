from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.schemas.reporting import ReportType
from app.services.reporting import ReportingService

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_reporting_service_bounds_page_and_requires_report_permission():
    service = ReportingService.__new__(ReportingService)
    service.repository = type("Repository", (), {})()
    service.repository.applications = AsyncMock(
        return_value=[{"group": "SUBMITTED", "count": 2}] * 201
    )

    rows, has_more = await service.generate(
        actor_role="SUPER_ADMIN",
        report_type=ReportType.APPLICATIONS,
        start_at=None,
        end_at=None,
        limit=200,
        offset=0,
    )

    assert len(rows) == 200
    assert has_more is True


@pytest.mark.asyncio
async def test_reporting_service_rejects_unauthorized_role():
    service = ReportingService.__new__(ReportingService)
    service.repository = type("Repository", (), {"applications": AsyncMock()})()

    with pytest.raises(PermissionError):
        await service.generate(
            actor_role="UNDERWRITER",
            report_type=ReportType.APPLICATIONS,
            start_at=datetime(2026, 1, 1),
            end_at=None,
            limit=10,
            offset=0,
        )


@pytest.mark.asyncio
async def test_reporting_service_rejects_unbounded_date_range():
    service = ReportingService.__new__(ReportingService)
    service.repository = type("Repository", (), {"applications": AsyncMock()})()

    with pytest.raises(ValueError, match="366 days"):
        await service.generate(
            actor_role="SUPER_ADMIN",
            report_type=ReportType.APPLICATIONS,
            start_at=datetime(2024, 1, 1),
            end_at=datetime(2026, 1, 1),
            limit=10,
            offset=0,
        )
