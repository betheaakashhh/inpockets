from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=30)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str | None
    last_name: str | None
    date_of_birth: date | None
    gender: str | None
    created_at: datetime
    updated_at: datetime


class OnboardingStepUpdateRequest(BaseModel):
    current_step: str = Field(..., min_length=1, max_length=30)


class OnboardingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    current_step: str
    created_at: datetime
    updated_at: datetime


class ConsentRequest(BaseModel):
    consent_type: str = Field(..., min_length=1, max_length=50)
    version: str = Field(..., min_length=1, max_length=30)
    status: str = Field(..., min_length=1, max_length=30)