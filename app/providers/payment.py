"""Repayment (collection) provider abstraction, vendor-neutral.

The provider (or our own server-to-server lookup) is the only source of truth
for whether a customer's money arrived. A browser redirect, an app callback or
any client-supplied "success" is never evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class PaymentProviderError(Exception):
    pass


class PaymentProviderTimeout(PaymentProviderError):
    """No usable response; the payment may or may not exist. Never assume."""


class PaymentProviderRejected(PaymentProviderError):
    """Provider definitively refused to create the payment."""

    def __init__(self, message: str = "", code: str = "PROVIDER_REJECTED"):
        super().__init__(message)
        self.code = code


class PaymentSignatureInvalid(PaymentProviderError):
    pass


class PaymentCallbackMalformed(PaymentProviderError):
    pass


@dataclass(frozen=True)
class PaymentCreateResult:
    provider_ref: str
    status: str  # PENDING | SUCCESS | FAILED
    checkout_url: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class PaymentStatusResult:
    status: str  # NOT_FOUND | PENDING | SUCCESS | FAILED | REVERSED
    provider_ref: str | None = None
    amount: Decimal | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class PaymentCallback:
    """A verified provider callback."""

    event_id: str
    provider_ref: str
    status: str  # PENDING | SUCCESS | FAILED | REVERSED
    idempotency_key: str | None = None
    amount: Decimal | None = None
    occurred_at: datetime | None = None
    failure_code: str | None = None


class PaymentProvider(ABC):
    name: str
    supports_polling: bool = True

    @abstractmethod
    async def create_payment(
        self,
        *,
        idempotency_key: str,
        amount: Decimal,
        currency: str,
        reference: str,
    ) -> PaymentCreateResult:
        """Open a collection. MUST be idempotent on `idempotency_key`."""

    @abstractmethod
    async def get_status(
        self, *, idempotency_key: str, provider_ref: str | None
    ) -> PaymentStatusResult: ...

    @abstractmethod
    def verify_webhook(self, *, headers, body: bytes) -> PaymentCallback:
        """Authenticate and parse a callback (raises PaymentSignatureInvalid /
        PaymentCallbackMalformed)."""
