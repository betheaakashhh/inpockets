"""Development payment provider (never allowed in production).

Idempotent on the idempotency key. Test controls:

  behaviour = "ok"             create -> PENDING (final state arrives later)
              "instant"        create -> SUCCESS
              "fail"           create -> FAILED (BANK_DECLINED)
              "reject"         create raises Rejected (nothing created)
              "timeout_before" create raises Timeout, nothing created
              "timeout_after"  payment IS created, then create raises Timeout
              "down"           every call raises Timeout
`transactions` is the provider-side record; tests mutate it to simulate the
customer paying, and assert it never holds two payments for one key.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.providers import webhook_signature
from app.providers.payment import (
    PaymentCallback,
    PaymentCallbackMalformed,
    PaymentCreateResult,
    PaymentProvider,
    PaymentProviderRejected,
    PaymentProviderTimeout,
    PaymentSignatureInvalid,
    PaymentStatusResult,
)

TIMESTAMP_HEADER = "x-payment-timestamp"
SIGNATURE_HEADER = "x-payment-signature"
_STATUSES = {"PENDING", "SUCCESS", "FAILED", "REVERSED"}


def sign_webhook(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts, digest = webhook_signature.sign(secret, body, timestamp)
    return {"X-Payment-Timestamp": ts, "X-Payment-Signature": digest}


class DevelopmentPaymentProvider(PaymentProvider):
    name = "development"

    behaviour: str = "ok"
    transactions: dict[str, dict] = {}
    create_calls: list[str] = []

    def __init__(self, *, webhook_secret: str | None, tolerance_seconds: int):
        self._secret = webhook_secret
        self._tolerance = tolerance_seconds

    @classmethod
    def reset(cls) -> None:
        cls.behaviour = "ok"
        cls.transactions = {}
        cls.create_calls = []

    @staticmethod
    def ref_for(key: str) -> str:
        return "dev-pay-" + hashlib.sha256(key.encode()).hexdigest()[:24]

    async def create_payment(self, *, idempotency_key, amount, currency, reference):
        self.create_calls.append(idempotency_key)
        if self.behaviour == "down":
            raise PaymentProviderTimeout("provider unreachable")
        if self.behaviour == "reject":
            raise PaymentProviderRejected("rejected", code="PROVIDER_REJECTED")
        if self.behaviour == "timeout_before":
            raise PaymentProviderTimeout("timed out before creating")

        tx = self.transactions.get(idempotency_key)
        if tx is None:  # first time: exactly one payment per key
            status = {"instant": "SUCCESS", "fail": "FAILED"}.get(self.behaviour, "PENDING")
            tx = {
                "provider_ref": self.ref_for(idempotency_key),
                "status": status,
                "amount": Decimal(amount),
                "failure_code": "BANK_DECLINED" if status == "FAILED" else None,
            }
            self.transactions[idempotency_key] = tx
        if self.behaviour == "timeout_after":
            raise PaymentProviderTimeout("timed out after creating")
        return PaymentCreateResult(
            provider_ref=tx["provider_ref"],
            status=tx["status"],
            checkout_url=f"https://pay.dev.invalid/{tx['provider_ref']}",
            failure_code=tx["failure_code"],
        )

    async def get_status(self, *, idempotency_key, provider_ref) -> PaymentStatusResult:
        if self.behaviour == "down":
            raise PaymentProviderTimeout("provider unreachable")
        tx = self.transactions.get(idempotency_key)
        if tx is None:
            return PaymentStatusResult(status="NOT_FOUND")
        return PaymentStatusResult(
            status=tx["status"],
            provider_ref=tx["provider_ref"],
            amount=tx["amount"],
            failure_code=tx["failure_code"],
        )

    def verify_webhook(self, *, headers, body: bytes) -> PaymentCallback:
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
            raise PaymentSignatureInvalid(str(exc)) from exc
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
            raise PaymentCallbackMalformed("unusable callback body") from exc
        if status not in _STATUSES or not event_id or not provider_ref:
            raise PaymentCallbackMalformed("unusable callback body")
        return PaymentCallback(
            event_id=event_id,
            provider_ref=provider_ref,
            status=status,
            idempotency_key=data.get("idempotency_key") or None,
            amount=amount,
            occurred_at=occurred,
            failure_code=data.get("failure_code") or None,
        )
