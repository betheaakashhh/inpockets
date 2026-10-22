from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.domain.bank_verification import mask_account
from app.domain.disbursement import CUSTOMER_STATUS, DisbursementStatus


class DisbursementResponse(BaseModel):
    """Customer view: no provider detail, no internal uncertainty."""

    id: uuid.UUID
    loan_offer_id: uuid.UUID
    status: str
    amount: Decimal
    currency: str
    account_number_masked: str
    ifsc: str
    utr: str | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_row(cls, d) -> DisbursementResponse:
        status = DisbursementStatus(d.status)
        return cls(
            id=d.id,
            loan_offer_id=d.loan_offer_id,
            status=CUSTOMER_STATUS[status],
            amount=d.amount,
            currency=d.currency,
            account_number_masked=mask_account(d.beneficiary_last4),
            ifsc=d.beneficiary_ifsc,
            utr=d.utr if status in (DisbursementStatus.SUCCESS, DisbursementStatus.REVERSED) else None,
            completed_at=d.completed_at,
        )


class DisbursementEventResponse(BaseModel):
    provider_event_id: str
    reported_status: str
    outcome: str
    received_at: datetime


class AdminDisbursementResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    loan_application_id: uuid.UUID
    loan_offer_id: uuid.UUID
    loan_offer_version: int
    esign_transaction_id: uuid.UUID
    bank_verification_id: uuid.UUID
    status: str
    amount: Decimal
    currency: str
    account_number_masked: str
    ifsc: str
    attempt: int
    retry_of_id: uuid.UUID | None
    idempotency_key: str
    provider: str
    provider_ref: str | None
    utr: str | None
    failure_code: str | None
    review_reason: str | None
    dispatch_attempts: int
    requested_at: datetime
    dispatched_at: datetime | None
    last_polled_at: datetime | None
    completed_at: datetime | None
    reversed_at: datetime | None
    events: list[DisbursementEventResponse] = []

    @classmethod
    def from_row(cls, d, events=()) -> AdminDisbursementResponse:
        return cls(
            id=d.id,
            user_id=d.user_id,
            loan_application_id=d.loan_application_id,
            loan_offer_id=d.loan_offer_id,
            loan_offer_version=d.loan_offer_version,
            esign_transaction_id=d.esign_transaction_id,
            bank_verification_id=d.bank_verification_id,
            status=d.status,
            amount=d.amount,
            currency=d.currency,
            account_number_masked=mask_account(d.beneficiary_last4),
            ifsc=d.beneficiary_ifsc,
            attempt=d.attempt,
            retry_of_id=d.retry_of_id,
            idempotency_key=d.idempotency_key,
            provider=d.provider,
            provider_ref=d.provider_ref,
            utr=d.utr,
            failure_code=d.failure_code,
            review_reason=d.review_reason,
            dispatch_attempts=d.dispatch_attempts,
            requested_at=d.requested_at,
            dispatched_at=d.dispatched_at,
            last_polled_at=d.last_polled_at,
            completed_at=d.completed_at,
            reversed_at=d.reversed_at,
            events=[
                DisbursementEventResponse(
                    provider_event_id=e.provider_event_id,
                    reported_status=e.reported_status,
                    outcome=e.outcome,
                    received_at=e.received_at,
                )
                for e in events
            ],
        )


class DisbursementCreateRequest(BaseModel):
    """Only the offer is named: amount and beneficiary come from stored records."""

    model_config = ConfigDict(extra="forbid")

    loan_offer_id: uuid.UUID


class DisbursementRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class DisbursementRecheckResponse(BaseModel):
    outcome: str
    disbursement: AdminDisbursementResponse
