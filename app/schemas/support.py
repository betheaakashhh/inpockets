from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.support import Category, Kind, Priority, Status


class TicketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    category: Category
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=1, max_length=2000)
    loan_application_id: uuid.UUID | None = None
    loan_offer_id: uuid.UUID | None = None


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class CustomerEvent(BaseModel):
    """What a customer sees of the history: who spoke, what, when. Nothing internal."""

    event_type: str
    from_: str = Field(alias="from")
    body: str | None
    created_at: datetime

    model_config = ConfigDict(populate_by_name=True)


class CustomerTicket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_number: str
    kind: str
    category: str
    subject: str
    status: str
    loan_application_id: uuid.UUID | None
    loan_offer_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class CustomerTicketDetail(CustomerTicket):
    events: list[CustomerEvent]


class AdminTicket(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_number: str
    user_id: uuid.UUID
    kind: str
    category: str
    sensitive: bool
    subject: str
    status: str
    priority: str
    loan_application_id: uuid.UUID | None
    loan_offer_id: uuid.UUID | None
    assigned_to_admin_user_id: uuid.UUID | None
    assigned_at: datetime | None
    escalation_level: int
    sla_due_at: datetime | None
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    overdue: bool = False


class AdminEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    visibility: str
    actor_type: str
    actor_admin_user_id: uuid.UUID | None
    body: str | None
    payload: dict | None
    created_at: datetime


class AdminTicketDetail(AdminTicket):
    customer_phone_masked: str
    events: list[AdminEvent]


class SummaryRow(BaseModel):
    status: str
    kind: str
    count: int


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_admin_user_id: uuid.UUID | None = None


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=3, max_length=2000)


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    note: str | None = Field(default=None, max_length=2000)


class PriorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Priority


class EscalateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=2000)


class ContactResponse(BaseModel):
    phone_number: str
