from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_type: str
    owner_type: str
    owner_id: UUID
    content_type: str
    size_bytes: int
    version: int
    is_immutable: bool
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]