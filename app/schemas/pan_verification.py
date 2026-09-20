from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PANVerificationRequest(BaseModel):
    pan_number: str = Field(..., min_length=10, max_length=10)


class PANVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    pan_number_masked: str
    provider: str
    verified_name: str | None
    name_match_result: str | None
    failure_reason: str | None
    created_at: datetime
