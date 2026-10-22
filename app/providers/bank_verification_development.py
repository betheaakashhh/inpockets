"""Development bank verification provider. Never allowed in production.

Deterministic by the LAST FOUR DIGITS of the account number:
  0000 -> FAILED (ACCOUNT_NOT_FOUND)
  1111 -> PENDING; resolved later through `get_status` (test-controlled)
  2222 -> VERIFIED but name MISMATCH
  3333 -> VERIFIED but name PARTIAL
  4444 -> VERIFIED but name UNAVAILABLE
  anything else -> VERIFIED, name MATCH
"""

from __future__ import annotations

import hashlib

from app.providers.bank_verification import (
    BankAccountVerificationProvider,
    BankProviderRejected,
    BankProviderTimeout,
    BankVerificationResult,
)


class DevelopmentBankVerificationProvider(BankAccountVerificationProvider):
    name = "development"

    # Test controls (process-local).
    behaviour: str = "ok"  # ok | timeout | reject
    records: dict[str, BankVerificationResult] = {}
    calls: list[str] = []

    @classmethod
    def reset(cls) -> None:
        cls.behaviour = "ok"
        cls.records = {}
        cls.calls = []

    async def verify(
        self,
        *,
        client_reference: str,
        account_number: str,
        ifsc: str,
        account_holder_name: str,
    ) -> BankVerificationResult:
        self.calls.append(client_reference)
        if self.behaviour == "timeout":
            raise BankProviderTimeout("provider timed out")
        if self.behaviour == "reject":
            raise BankProviderRejected("provider rejected the request")
        ref = "dev-bank-" + hashlib.sha256(client_reference.encode()).hexdigest()[:24]
        if ref in self.records:  # idempotent on client_reference
            return self.records[ref]
        tail = account_number[-4:]
        if tail == "0000":
            result = BankVerificationResult(
                ref, "FAILED", failure_code="ACCOUNT_NOT_FOUND"
            )
        elif tail == "1111":
            result = BankVerificationResult(ref, "PENDING")
        else:
            match = {"2222": "MISMATCH", "3333": "PARTIAL", "4444": "UNAVAILABLE"}.get(
                tail, "MATCH"
            )
            result = BankVerificationResult(
                ref, "VERIFIED", name_match_result=match, bank_name="Dev Test Bank"
            )
        self.records[ref] = result
        return result

    async def get_status(self, *, provider_ref: str) -> BankVerificationResult:
        if self.behaviour == "timeout":
            raise BankProviderTimeout("provider timed out")
        result = self.records.get(provider_ref)
        if result is None:
            raise BankProviderRejected("unknown verification")
        return result
