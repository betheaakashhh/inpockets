from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ReportType(StrEnum):
    APPLICATIONS = "applications"
    DECISIONS = "decisions"
    DISBURSEMENTS = "disbursements"
    EXPOSURE = "exposure"
    REPAYMENTS = "repayments"
    OVERDUE = "overdue"
    COLLECTIONS = "collections"
    CLOSURES = "closures"
    PROVIDER_FAILURES = "provider_failures"
    RECONCILIATION = "reconciliation"
    RISK_FRAUD = "risk_fraud"


class ReportResponse(BaseModel):
    report_type: ReportType
    generated_at: datetime
    rows: list[dict[str, Any]]
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
