from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.domain.esign import CUSTOMER_STATUS, ESignStatus


class ESignResponse(BaseModel):
    """Customer view: no provider internals or failure detail."""

    id: uuid.UUID
    loan_offer_id: uuid.UUID
    loan_offer_version: int
    status: str
    signing_url: str | None = None
    expires_at: datetime
    signed_at: datetime | None = None

    @classmethod
    def from_tx(cls, tx, signing_url: str | None = None) -> ESignResponse:
        return cls(
            id=tx.id,
            loan_offer_id=tx.loan_offer_id,
            loan_offer_version=tx.loan_offer_version,
            status=CUSTOMER_STATUS[ESignStatus(tx.status)],
            signing_url=signing_url,
            expires_at=tx.expires_at,
            signed_at=tx.signed_at,
        )


class ESignEventResponse(BaseModel):
    provider_event_id: str
    reported_status: str
    outcome: str
    received_at: datetime


class AdminESignResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    loan_offer_id: uuid.UUID
    loan_offer_version: int
    document_id: uuid.UUID
    document_checksum: str
    provider: str
    provider_ref: str | None
    status: str
    failure_reason: str | None
    signed_document_id: uuid.UUID | None
    signed_checksum: str | None
    signed_at: datetime | None
    expires_at: datetime
    events: list[ESignEventResponse]

    @classmethod
    def from_tx(cls, tx, events) -> AdminESignResponse:
        return cls(
            id=tx.id,
            user_id=tx.user_id,
            loan_offer_id=tx.loan_offer_id,
            loan_offer_version=tx.loan_offer_version,
            document_id=tx.document_id,
            document_checksum=tx.document_checksum,
            provider=tx.provider,
            provider_ref=tx.provider_ref,
            status=tx.status,
            failure_reason=tx.failure_reason,
            signed_document_id=tx.signed_document_id,
            signed_checksum=tx.signed_checksum,
            signed_at=tx.signed_at,
            expires_at=tx.expires_at,
            events=[
                ESignEventResponse(
                    provider_event_id=e.provider_event_id,
                    reported_status=e.reported_status,
                    outcome=e.outcome,
                    received_at=e.received_at,
                )
                for e in events
            ],
        )
