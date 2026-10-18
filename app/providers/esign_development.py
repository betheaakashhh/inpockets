"""Development e-sign provider: deterministic, in-memory, HMAC-signed callbacks.

Never usable in production (enforced by the factory). Tests drive "the
provider" through the class-level `STATE` and `sign_callback` helper.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from datetime import datetime

from app.providers.esign import (
    ESignCallback,
    ESignCallbackMalformed,
    ESignInitiation,
    ESignProvider,
    ESignProviderRejected,
    ESignProviderTimeout,
    ESignSignatureInvalid,
    ESignStatusResult,
)

TIMESTAMP_HEADER = "x-esign-timestamp"
SIGNATURE_HEADER = "x-esign-signature"
_STATUSES = {"PENDING", "SIGNED", "FAILED", "EXPIRED"}


def sign_callback(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Headers a legitimate provider would attach to `body`."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {"X-ESign-Timestamp": ts, "X-ESign-Signature": digest}


class DevelopmentESignProvider(ESignProvider):
    name = "development"

    # Test controls (process-local).
    behaviour: str = "ok"  # ok | timeout | reject
    transactions: dict[str, dict] = {}

    def __init__(self, *, webhook_secret: str | None, tolerance_seconds: int):
        self._secret = webhook_secret
        self._tolerance = tolerance_seconds

    @classmethod
    def reset(cls) -> None:
        cls.behaviour = "ok"
        cls.transactions = {}

    async def initiate(
        self,
        *,
        client_reference: str,
        signer_user_id: str,
        document: bytes,
        document_name: str,
        document_checksum: str,
    ) -> ESignInitiation:
        if self.behaviour == "timeout":
            raise ESignProviderTimeout("provider timed out")
        if self.behaviour == "reject":
            raise ESignProviderRejected("provider rejected the document")
        ref = "dev-esign-" + hashlib.sha256(client_reference.encode()).hexdigest()[:24]
        self.transactions.setdefault(
            ref,
            {
                "status": "PENDING",
                "document_checksum": document_checksum,
                "signed": None,
            },
        )
        return ESignInitiation(
            provider_ref=ref, signing_url=f"https://esign.invalid/sign/{ref}"
        )

    async def get_status(self, *, provider_ref: str) -> ESignStatusResult:
        if self.behaviour == "timeout":
            raise ESignProviderTimeout("provider timed out")
        tx = self.transactions.get(provider_ref)
        if tx is None:
            raise ESignProviderRejected("unknown transaction")
        return ESignStatusResult(
            provider_ref=provider_ref,
            status=tx["status"],
            document_checksum=tx["document_checksum"],
        )

    async def get_signing_url(self, *, provider_ref: str) -> str | None:
        return f"https://esign.invalid/sign/{provider_ref}"

    async def fetch_signed_document(self, *, provider_ref: str) -> bytes | None:
        tx = self.transactions.get(provider_ref)
        return None if tx is None else tx["signed"]

    def verify_callback(
        self, *, headers: Mapping[str, str], body: bytes
    ) -> ESignCallback:
        if not self._secret:
            # Fail closed: no secret configured means nothing is trusted.
            raise ESignSignatureInvalid("webhook secret not configured")
        lowered = {k.lower(): v for k, v in headers.items()}
        ts, sig = lowered.get(TIMESTAMP_HEADER), lowered.get(SIGNATURE_HEADER)
        if not ts or not sig:
            raise ESignSignatureInvalid("missing signature headers")
        try:
            ts_int = int(ts)
        except ValueError as exc:
            raise ESignSignatureInvalid("bad timestamp") from exc
        if abs(time.time() - ts_int) > self._tolerance:
            raise ESignSignatureInvalid("timestamp outside tolerance")
        expected = hmac.new(
            self._secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ESignSignatureInvalid("signature mismatch")

        try:
            data = json.loads(body)
            event_id = str(data["event_id"])
            provider_ref = str(data["provider_ref"])
            status = str(data["status"]).upper()
        except (ValueError, KeyError, TypeError) as exc:
            raise ESignCallbackMalformed("unusable callback body") from exc
        if status not in _STATUSES or not event_id or not provider_ref:
            raise ESignCallbackMalformed("unusable callback body")
        signed = None
        if data.get("signed_document_b64"):
            try:
                signed = base64.b64decode(data["signed_document_b64"], validate=True)
            except ValueError as exc:
                raise ESignCallbackMalformed("bad signed document encoding") from exc
        occurred = None
        if data.get("occurred_at"):
            try:
                occurred = datetime.fromisoformat(data["occurred_at"])
            except ValueError as exc:
                raise ESignCallbackMalformed("bad occurred_at") from exc
        return ESignCallback(
            event_id=event_id,
            provider_ref=provider_ref,
            status=status,
            document_checksum=data.get("document_checksum"),
            occurred_at=occurred,
            failure_reason=(data.get("failure_reason") or None),
            signed_document=signed,
        )
