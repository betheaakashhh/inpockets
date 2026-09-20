from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class KYCDocumentResponse(BaseModel):
    id: UUID
    kyc_record_id: UUID
    document_id: UUID
    provider_document_ref: str
    document_type: str
    retrieved_at: datetime


class KYCDocumentListResponse(BaseModel):
    items: list[KYCDocumentResponse]
