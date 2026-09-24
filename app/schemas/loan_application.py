from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field #type: ignore

from app.domain.loan_application import LoanApplicationStatus


class LoanApplicationCreateRequest(BaseModel):
    requested_amount: Decimal = Field(gt=0)
    requested_tenure_days: int = Field(gt=0)


class LoanApplicationResponse(BaseModel):
    id: uuid.UUID
    application_number: str
    user_id: uuid.UUID
    status: LoanApplicationStatus
    requested_amount: Decimal
    requested_tenure_days: int
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LoanApplicationEventResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    event_type: str
    previous_status: str | None
    new_status: str
    actor_type: str
    actor_id: uuid.UUID | None
    reason: str | None
    event_metadata: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}