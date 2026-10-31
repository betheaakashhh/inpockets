from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.collections import Channel, ContactOutcome, NextAction


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    loan_offer_id: uuid.UUID
    schedule_id: uuid.UUID
    oldest_installment_id: uuid.UUID
    status: str
    dpd: int
    dpd_bucket: str | None
    overdue_principal: Decimal
    overdue_interest: Decimal
    overdue_fees: Decimal
    escalation_level: int
    assigned_to_admin_user_id: uuid.UUID | None
    assigned_at: datetime | None
    next_action: str | None
    next_action_at: datetime | None
    last_contact_at: datetime | None
    last_reminder_at: datetime | None
    close_reason: str | None
    opened_at: datetime
    closed_at: datetime | None


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    installment_id: uuid.UUID | None
    event_type: str
    actor_type: str
    actor_admin_user_id: uuid.UUID | None
    channel: str | None
    template_key: str | None
    note: str | None
    payload: dict | None
    created_at: datetime


class CaseDetailResponse(CaseResponse):
    events: list[EventResponse]


class SummaryRow(BaseModel):
    status: str
    bucket: str | None
    cases: int
    overdue_total: Decimal


class SummaryResponse(BaseModel):
    total_cases: int
    rows: list[SummaryRow]


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # AdminUser id to assign to. Omit to take the case yourself.
    assignee_admin_user_id: uuid.UUID | None = None


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=3, max_length=2000)


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel
    outcome: ContactOutcome
    note: str | None = Field(default=None, max_length=2000)


class NextActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: NextAction
    due_at: datetime
    note: str | None = Field(default=None, max_length=2000)


class EscalateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=2000)
