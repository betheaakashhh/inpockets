from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from app.domain.bank_verification import (
    ACCOUNT_NUMBER_PATTERN,
    CUSTOMER_STATUS,
    CUSTOMER_VISIBLE_FAILURE_CODES,
    IFSC_PATTERN,
    BankVerificationStatus,
    mask_account,
)


class BankVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # SecretStr keeps the number out of repr()/logs of this object.
    account_number: SecretStr
    ifsc: str

    @field_validator("account_number")
    @classmethod
    def _account(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value().strip().replace(" ", "")
        if not ACCOUNT_NUMBER_PATTERN.fullmatch(raw):
            raise ValueError("Invalid account number")
        return SecretStr(raw)

    @field_validator("ifsc")
    @classmethod
    def _ifsc(cls, v: str) -> str:
        v = v.strip().upper()
        if not IFSC_PATTERN.fullmatch(v):
            raise ValueError("Invalid IFSC")
        return v


class BankVerificationResponse(BaseModel):
    """Customer view. Masked account, no provider detail, no internal codes."""

    id: uuid.UUID
    status: str
    account_number_masked: str
    ifsc: str
    bank_name: str | None = None
    failure_code: str | None = None
    requested_at: datetime
    verified_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> BankVerificationResponse:
        code = row.failure_code if row.failure_code in CUSTOMER_VISIBLE_FAILURE_CODES else None
        return cls(
            id=row.id,
            status=CUSTOMER_STATUS[BankVerificationStatus(row.status)],
            account_number_masked=mask_account(row.account_last4),
            ifsc=row.ifsc,
            bank_name=row.bank_name,
            failure_code=code,
            requested_at=row.requested_at,
            verified_at=row.verified_at,
        )


class AdminBankVerificationResponse(BaseModel):
    """Admin view: still masked. There is no endpoint that returns the number."""

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    account_number_masked: str
    ifsc: str
    bank_name: str | None
    provider: str
    provider_ref: str | None
    name_match_result: str | None
    failure_code: str | None
    resolution_reason: str | None
    reviewed_by_admin_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    verified_at: datetime | None
    superseded_at: datetime | None
    requested_at: datetime
    expires_at: datetime

    @classmethod
    def from_row(cls, row) -> AdminBankVerificationResponse:
        return cls(
            id=row.id,
            user_id=row.user_id,
            status=row.status,
            account_number_masked=mask_account(row.account_last4),
            ifsc=row.ifsc,
            bank_name=row.bank_name,
            provider=row.provider,
            provider_ref=row.provider_ref,
            name_match_result=row.name_match_result,
            failure_code=row.failure_code,
            resolution_reason=row.resolution_reason,
            reviewed_by_admin_user_id=row.reviewed_by_admin_user_id,
            reviewed_at=row.reviewed_at,
            verified_at=row.verified_at,
            superseded_at=row.superseded_at,
            requested_at=row.requested_at,
            expires_at=row.expires_at,
        )


class BankVerificationResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    reason: str
