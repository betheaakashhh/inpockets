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


@pytest.mark.asyncio
async def test_reporting_service_rejects_historical_exposure():
    service = ReportingService.__new__(ReportingService)
    service.repository = type("Repository", (), {"exposure": AsyncMock()})()

    with pytest.raises(ValueError, match="historical exposure"):
        await service.generate(
            actor_role="SUPER_ADMIN",
            report_type=ReportType.EXPOSURE,
            start_at=datetime(2026, 1, 1),
            end_at=datetime(2026, 1, 2),
            limit=10,
            offset=0,
        )


@pytest.mark.asyncio
async def test_reporting_service_rejects_historical_overdue_snapshot():
    service = ReportingService.__new__(ReportingService)
    service.repository = type("Repository", (), {"overdue": AsyncMock()})()

    with pytest.raises(ValueError, match="current snapshot"):
        await service.generate(
            actor_role="SUPER_ADMIN",
            report_type=ReportType.OVERDUE,
            start_at=datetime(2026, 1, 1),
            end_at=datetime(2026, 1, 2),
            limit=10,
            offset=0,
        )


@pytest.mark.asyncio
async def test_reporting_service_requires_category_permission():
    service = ReportingService.__new__(ReportingService)
    service.repository = type("Repository", (), {"risk_fraud": AsyncMock()})()

    with pytest.raises(PermissionError):
        await service.generate(
            actor_role="FINANCE",
            report_type=ReportType.RISK_FRAUD,
            start_at=None,
            end_at=None,
            limit=10,
            offset=0,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "report_type", "allowed"),
    [
        ("FINANCE", ReportType.REPAYMENTS, True),
        ("FINANCE", ReportType.RISK_FRAUD, False),
        ("SENIOR_UNDERWRITER", ReportType.RISK_FRAUD, True),
        ("COLLECTIONS_AGENT", ReportType.COLLECTIONS, False),
        ("AUDITOR", ReportType.COLLECTIONS, True),
    ],
)
async def test_reporting_permission_matrix(role, report_type, allowed):
    service = ReportingService.__new__(ReportingService)
    method = report_type.value
    service.repository = type("Repository", (), {method: AsyncMock(return_value=[])})()

    if allowed:
        await service.generate(
            actor_role=role,
            report_type=report_type,
            start_at=None,
            end_at=None,
            limit=10,
            offset=0,
        )
    else:
        with pytest.raises(PermissionError):
            await service.generate(
                actor_role=role,
                report_type=report_type,
                start_at=None,
                end_at=None,
                limit=10,
                offset=0,
            )
