from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

import app.domain.loan_offer as offer_domain
from app.domain.loan_offer import effective_offer_status

# Money/rate terms are strings (e.g. "12.5") or ints, never floats.
TermValue = StrictStr | StrictInt | StrictBool
MAX_TERMS = 50


class LoanOfferDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loan_application_id: uuid.UUID
    principal_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    tenure_days: int = Field(gt=0, le=3650)
    commercial_terms: dict[
        Annotated[str, Field(min_length=1, max_length=100)],
        Annotated[TermValue, Field()],
    ]

    @field_validator("commercial_terms")
    @classmethod
    def _bounded_terms(cls, terms: dict) -> dict:
        if len(terms) > MAX_TERMS:
            raise ValueError(f"at most {MAX_TERMS} commercial terms allowed")
        for value in terms.values():
            if isinstance(value, str) and len(value) > 500:
                raise ValueError("commercial term values are limited to 500 chars")
        return terms


class LoanOfferIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional override of the configured default validity window.
    validity_hours: int | None = Field(default=None, ge=1, le=24 * 30)

    def validity(self) -> timedelta | None:
        return None if self.validity_hours is None else timedelta(hours=self.validity_hours)


class LoanOfferCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value.strip()


class LoanOfferAcceptRequest(BaseModel):
    """The customer echoes what they were shown; the server verifies it."""

    model_config = ConfigDict(extra="forbid")

    offer_version: int = Field(ge=1)
    kfs_document_id: uuid.UUID
    kfs_acknowledged: bool

    @model_validator(mode="after")
    def _must_acknowledge(self) -> LoanOfferAcceptRequest:
        if not self.kfs_acknowledged:
            raise ValueError("the Key Facts Statement must be acknowledged")
        return self


class _OfferBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    loan_application_id: uuid.UUID
    version: int
    principal_amount: Decimal
    tenure_days: int
    commercial_terms: dict
    issued_at: datetime | None
    expires_at: datetime | None
    accepted_at: datetime | None
    kfs_document_id: uuid.UUID | None
    agreement_document_id: uuid.UUID | None
    created_at: datetime


class LoanOfferResponse(_OfferBase):
    """Customer view. `status` is effective (ISSUED past expiry => EXPIRED)."""

    status: str

    @classmethod
    def from_offer(cls, offer) -> LoanOfferResponse:
        data = cls.model_validate(offer)
        data.status = effective_offer_status(
            status=offer.status,
            expires_at=offer.expires_at,
            now=offer_domain.utcnow(),
        )
        return data


class AdminLoanOfferResponse(_OfferBase):
    """Admin view: shows the stored status and effective status separately."""

    status: str
    effective_status: str = ""
    user_id: uuid.UUID
    created_by_admin_user_id: uuid.UUID | None

    @classmethod
    def from_offer(cls, offer) -> AdminLoanOfferResponse:
        data = cls.model_validate(offer)
        data.effective_status = effective_offer_status(
            status=offer.status,
            expires_at=offer.expires_at,
            now=offer_domain.utcnow(),
        )
        return data
