"""Development disbursement provider (never allowed in production).

Idempotent on the idempotency key, with test controls for the failure modes
that matter for money movement:

  behaviour = "ok"            submit -> PROCESSING (final state arrives later)
              "instant"       submit -> SUCCESS
              "fail"          submit -> FAILED (BANK_DECLINED)
              "reject"        submit raises Rejected (nothing created)
              "timeout_before" submit raises Timeout, nothing created
              "timeout_after"  payout IS created, then submit raises Timeout
              "down"          every call raises Timeout
`transactions` is the provider-side ledger; tests assert it never holds more
than one payout per key.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.providers import webhook_signature
from app.providers.disbursement import (
    DisbursementCallback,
    DisbursementCallbackMalformed,
    DisbursementProvider,
    DisbursementProviderRejected,
    DisbursementProviderTimeout,
    DisbursementSignatureInvalid,
    DisbursementStatusResult,
    DisbursementSubmitResult,
)

TIMESTAMP_HEADER = "x-disbursement-timestamp"
SIGNATURE_HEADER = "x-disbursement-signature"
_STATUSES = {"PROCESSING", "SUCCESS", "FAILED", "REVERSED"}


def sign_webhook(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts, digest = webhook_signature.sign(secret, body, timestamp)
    return {"X-Disbursement-Timestamp": ts, "X-Disbursement-Signature": digest}


class DevelopmentDisbursementProvider(DisbursementProvider):
    name = "development"

    behaviour: str = "ok"
    transactions: dict[str, dict] = {}
    submit_calls: list[str] = []

    def __init__(self, *, webhook_secret: str | None, tolerance_seconds: int):
        self._secret = webhook_secret
        self._tolerance = tolerance_seconds

    @classmethod
    def reset(cls) -> None:
        cls.behaviour = "ok"
        cls.transactions = {}
        cls.submit_calls = []

    @staticmethod
    def ref_for(key: str) -> str:
        return "dev-disb-" + hashlib.sha256(key.encode()).hexdigest()[:24]

    async def submit(
        self,
        *,
        idempotency_key,
        amount,
        currency,
        beneficiary_account_number,
        beneficiary_ifsc,
        beneficiary_name,
        narration,
    ) -> DisbursementSubmitResult:
        self.submit_calls.append(idempotency_key)
        if self.behaviour == "down":
            raise DisbursementProviderTimeout("provider unreachable")
        if self.behaviour == "reject":
            raise DisbursementProviderRejected("rejected", code="INVALID_BENEFICIARY")
        if self.behaviour == "timeout_before":
            raise DisbursementProviderTimeout("timed out before processing")

        tx = self.transactions.get(idempotency_key)
        if tx is None:  # first time: money moves exactly once per key
            status = {"instant": "SUCCESS", "fail": "FAILED"}.get(self.behaviour, "PROCESSING")
            tx = {
                "provider_ref": self.ref_for(idempotency_key),
                "status": status,
                "amount": Decimal(amount),
                "utr": f"UTR{hashlib.sha256(idempotency_key.encode()).hexdigest()[:12].upper()}"
                if status == "SUCCESS"
                else None,
                "failure_code": "BANK_DECLINED" if status == "FAILED" else None,
                "beneficiary_last4": beneficiary_account_number[-4:],
            }
            self.transactions[idempotency_key] = tx
        if self.behaviour == "timeout_after":
            raise DisbursementProviderTimeout("timed out after processing")
        return DisbursementSubmitResult(
            provider_ref=tx["provider_ref"],
            status=tx["status"],
            utr=tx["utr"],
            failure_code=tx["failure_code"],
        )

    async def get_status(self, *, idempotency_key, provider_ref) -> DisbursementStatusResult:
        if self.behaviour == "down":
            raise DisbursementProviderTimeout("provider unreachable")
        tx = self.transactions.get(idempotency_key)
        if tx is None:
            return DisbursementStatusResult(status="NOT_FOUND")
        return DisbursementStatusResult(
            status=tx["status"],
            provider_ref=tx["provider_ref"],
            utr=tx["utr"],
            amount=tx["amount"],
            failure_code=tx["failure_code"],
        )

    def verify_webhook(self, *, headers, body: bytes) -> DisbursementCallback:
        try:
            webhook_signature.verify(
                secret=self._secret,
                headers=headers,
                body=body,
                timestamp_header=TIMESTAMP_HEADER,
                signature_header=SIGNATURE_HEADER,
                tolerance_seconds=self._tolerance,
            )
        except webhook_signature.SignatureError as exc:
            raise DisbursementSignatureInvalid(str(exc)) from exc
        try:
            data = json.loads(body)
            event_id = str(data["event_id"])
            provider_ref = str(data["provider_ref"])
            status = str(data["status"]).upper()
            amount = Decimal(str(data["amount"])) if data.get("amount") is not None else None
            occurred = (
                datetime.fromisoformat(data["occurred_at"]) if data.get("occurred_at") else None
            )
        except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
            raise DisbursementCallbackMalformed("unusable callback body") from exc
        if status not in _STATUSES or not event_id or not provider_ref:
            raise DisbursementCallbackMalformed("unusable callback body")
        return DisbursementCallback(
            event_id=event_id,
            provider_ref=provider_ref,
            status=status,
            idempotency_key=data.get("idempotency_key") or None,
            amount=amount,
            utr=data.get("utr") or None,
            occurred_at=occurred,
            failure_code=data.get("failure_code") or None,
        )
