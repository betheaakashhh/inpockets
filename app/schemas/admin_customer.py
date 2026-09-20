from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdminCustomerSummary(BaseModel):
    customer_id: UUID
    phone_number: str
    status: str
    first_name: str | None
    last_name: str | None
    date_of_birth: date | None
    gender: str | None
    onboarding_status: str | None
    onboarding_step: str | None
    created_at: datetime
    pan_status: str | None = None
    pan_number_masked: str | None = None


class AdminCustomerListResponse(BaseModel):
    items: list[AdminCustomerSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class AdminCustomerDetail(AdminCustomerSummary):
    profile_id: UUID | None
    onboarding_id: UUID | None
    onboarding_created_at: datetime | None
    onboarding_updated_at: datetime | None
