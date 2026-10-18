"""E-sign provider abstraction.

No vendor is hard-coded. A concrete provider implements this interface; the
service layer never depends on vendor payload shapes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


class ESignProviderError(Exception):
    """Base class for provider failures."""


class ESignProviderTimeout(ESignProviderError):
    """No usable response; whether the provider acted is unknown. Retry."""


class ESignProviderRejected(ESignProviderError):
    """The provider definitively refused the request (no transaction exists)."""


class ESignSignatureInvalid(ESignProviderError):
    """Callback authenticity could not be established."""


class ESignCallbackMalformed(ESignProviderError):
    """Callback is authentic but its content is unusable."""


@dataclass(frozen=True)
class ESignInitiation:
    provider_ref: str
    signing_url: str | None = None


@dataclass(frozen=True)
class ESignStatusResult:
    provider_ref: str
    status: str  # PENDING | SIGNED | FAILED | EXPIRED (provider-neutral)
    document_checksum: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class ESignCallback:
    """A verified provider callback."""

    event_id: str
    provider_ref: str
    status: str  # PENDING | SIGNED | FAILED | EXPIRED
    document_checksum: str | None
    occurred_at: datetime | None
    failure_reason: str | None = None
    signed_document: bytes | None = None


class ESignProvider(ABC):
    name: str

    @abstractmethod
    async def initiate(
        self,
        *,
        client_reference: str,
        signer_user_id: str,
        document: bytes,
        document_name: str,
        document_checksum: str,
    ) -> ESignInitiation:
        """Create (or idempotently re-create) a signing transaction.

        Must be idempotent on `client_reference`.
        """

    @abstractmethod
    async def get_status(self, *, provider_ref: str) -> ESignStatusResult: ...

    @abstractmethod
    async def get_signing_url(self, *, provider_ref: str) -> str | None: ...

    @abstractmethod
    async def fetch_signed_document(self, *, provider_ref: str) -> bytes | None: ...

    @abstractmethod
    def verify_callback(
        self, *, headers: Mapping[str, str], body: bytes
    ) -> ESignCallback:
        """Authenticate and parse a callback.

        Raises ESignSignatureInvalid if authenticity fails and
        ESignCallbackMalformed if the verified body is unusable.
        """
