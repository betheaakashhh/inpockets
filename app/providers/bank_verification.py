"""Bank account verification provider abstraction (vendor-neutral)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class BankProviderError(Exception):
    pass


class BankProviderTimeout(BankProviderError):
    """No usable response; whether the provider acted is unknown. Retry."""


class BankProviderRejected(BankProviderError):
    """Provider definitively refused the request (no verification exists)."""


@dataclass(frozen=True)
class BankVerificationResult:
    provider_ref: str
    status: str  # PENDING | VERIFIED | FAILED (provider-neutral)
    name_match_result: str | None = None  # MATCH|PARTIAL|MISMATCH|UNAVAILABLE
    bank_name: str | None = None
    failure_code: str | None = None  # closed vocabulary, never free text


class BankAccountVerificationProvider(ABC):
    name: str

    @abstractmethod
    async def verify(
        self,
        *,
        client_reference: str,
        account_number: str,
        ifsc: str,
        account_holder_name: str,
    ) -> BankVerificationResult:
        """Start (or idempotently repeat) a verification.

        Must be idempotent on `client_reference`.
        """

    @abstractmethod
    async def get_status(self, *, provider_ref: str) -> BankVerificationResult: ...
