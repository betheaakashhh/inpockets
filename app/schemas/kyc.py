from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class KYCInitiationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    provider: str
    kyc_type: str
    consent_url: str | None = None
    initiated_at: datetime
    completed_at: datetime | None = None
    failure_reason: str | None = None


class KYCStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    provider: str
    kyc_type: str
    initiated_at: datetime
    completed_at: datetime | None = None
    failure_reason: str | None = None
