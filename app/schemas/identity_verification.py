from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IdentityVerificationCaptureRequest(BaseModel):
    capture_ref: str = Field(min_length=1, max_length=255)


class IdentityVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    provider_ref: str
    verification_type: str
    status: str
    confidence_score: float | None = None
    failure_reason: str | None = None
    created_at: datetime
    capture_session_token: str | None = None
