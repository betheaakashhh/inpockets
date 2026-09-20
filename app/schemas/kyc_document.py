from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class KYCDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kyc_record_id: UUID
    document_id: UUID
    provider_document_ref: str
    document_type: str
    retrieved_at: datetime


class KYCDocumentListResponse(BaseModel):
    items: list[KYCDocumentResponse]
