"""Disbursement provider abstraction (vendor-neutral).

The provider is the only source of truth for whether money moved. Callers
must treat every submit as possibly-succeeded until told otherwise.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class DisbursementProviderError(Exception):
    pass


class DisbursementProviderTimeout(DisbursementProviderError):
    """No usable response; money may or may not have moved. Never assume."""


class DisbursementProviderRejected(DisbursementProviderError):
    """Provider definitively refused; no money moved."""

    def __init__(self, message: str = "", code: str = "PROVIDER_REJECTED"):
        super().__init__(message)
        self.code = code


class DisbursementSignatureInvalid(DisbursementProviderError):
    pass


class DisbursementCallbackMalformed(DisbursementProviderError):
    pass


@dataclass(frozen=True)
class DisbursementSubmitResult:
    provider_ref: str
    status: str  # PROCESSING | SUCCESS | FAILED
    utr: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class DisbursementStatusResult:
    status: str  # NOT_FOUND | PROCESSING | SUCCESS | FAILED | REVERSED
    provider_ref: str | None = None
    utr: str | None = None
    amount: Decimal | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class DisbursementCallback:
    """A verified provider callback."""

    event_id: str
    provider_ref: str
    status: str  # PROCESSING | SUCCESS | FAILED | REVERSED
    idempotency_key: str | None = None
    amount: Decimal | None = None
    utr: str | None = None
    occurred_at: datetime | None = None
    failure_code: str | None = None


class DisbursementProvider(ABC):
    name: str
    supports_polling: bool = True

    @abstractmethod
    async def submit(
        self,
        *,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        beneficiary_account_number: str,
        beneficiary_ifsc: str,
        beneficiary_name: str,
        narration: str,
    ) -> DisbursementSubmitResult:
        """Send a payout. MUST be idempotent on `idempotency_key`."""

    @abstractmethod
    async def get_status(
        self, *, idempotency_key: str, provider_ref: str | None
    ) -> DisbursementStatusResult: ...

    @abstractmethod
    def verify_webhook(self, *, headers, body: bytes) -> DisbursementCallback:
        """Authenticate and parse a callback.

        Raises DisbursementSignatureInvalid / DisbursementCallbackMalformed.
        """
