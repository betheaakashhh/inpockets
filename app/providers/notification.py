"""Notification provider abstraction (SMS / email / push), vendor-neutral.

`send` MUST be idempotent on `idempotency_key`: repeating a call after a
timeout must never deliver the message twice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class NotificationProviderError(Exception):
    pass


class NotificationTransient(NotificationProviderError):
    """Timeout, outage or throttling: worth retrying. The message may or may
    not have been accepted; the idempotency key makes a retry safe."""


class NotificationPermanent(NotificationProviderError):
    """The provider definitively refused (bad number, blocked, bad content)."""

    def __init__(self, message: str = "", code: str = "PROVIDER_REJECTED"):
        super().__init__(message)
        self.code = code


class NotificationSignatureInvalid(NotificationProviderError):
    pass


class NotificationCallbackMalformed(NotificationProviderError):
    pass


@dataclass(frozen=True)
class SendResult:
    provider_ref: str


@dataclass(frozen=True)
class DeliveryReceipt:
    """A verified provider delivery callback."""

    event_id: str
    provider_ref: str
    status: str  # DELIVERED | FAILED
    occurred_at: datetime | None = None
    failure_code: str | None = None


class NotificationProvider(ABC):
    name: str

    @abstractmethod
    async def send(
        self, *, channel: str, destination: str, body: str, subject: str | None, idempotency_key: str
    ) -> SendResult: ...

    @abstractmethod
    def verify_webhook(self, *, headers, body: bytes) -> DeliveryReceipt:
        """Authenticate and parse a delivery receipt (raises
        NotificationSignatureInvalid / NotificationCallbackMalformed)."""
