from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.reconciliation import Flow, Resolution


class RunStartRequest(BaseModel):
    flow: Flow
    report_date: date


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flow: str
    provider: str
    report_date: date
    status: str
    attempts: int
    error: str | None
    internal_count: int
    external_count: int
    matched_count: int
    unmatched_count: int
    mismatch_count: int
    review_count: int
    started_at: datetime
    completed_at: datetime | None


class RunStartResponse(BaseModel):
    outcome: str  # COMPLETED | FAILED | SKIPPED
    reason: str
    run: RunResponse | None = None


class RecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    flow: str
    provider: str
    provider_ref: str
    status: str
    discrepancy: str | None
    detail: str
    internal_type: str | None
    internal_id: uuid.UUID | None
    internal_status: str | None
    internal_amount: Decimal | None
    ledger_net: Decimal | None
    expected_ledger_net: Decimal | None
    external_line_id: str | None
    external_status: str | None
    external_amount: Decimal | None
    external_count: int
    review_status: str
    resolution: str | None
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime


class ResolveRequest(BaseModel):
    resolution: Resolution
    note: str = Field(min_length=10, max_length=2000)


class OpenSummaryRow(BaseModel):
    flow: str
    status: str
    review_status: str
    count: int


class OpenSummaryResponse(BaseModel):
    total_open: int
    rows: list[OpenSummaryRow]
