"""Development notification provider (never allowed in production).

Records what it was asked to send in `sent` (one entry per idempotency key,
however many times it is called). `behaviour` simulates trouble:

  "ok"              accept
  "transient"       raise NotificationTransient (nothing sent)
  "timeout_after"   message IS accepted, then raise NotificationTransient
  "permanent"       raise NotificationPermanent (nothing sent)
  "permanent_for"   refuse only destinations listed in `bad_destinations`
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.providers import webhook_signature
from app.providers.notification import (
    DeliveryReceipt,
    NotificationCallbackMalformed,
    NotificationPermanent,
    NotificationProvider,
    NotificationSignatureInvalid,
    NotificationTransient,
    SendResult,
)

TIMESTAMP_HEADER = "x-notification-timestamp"
SIGNATURE_HEADER = "x-notification-signature"


def sign_webhook(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts, digest = webhook_signature.sign(secret, body, timestamp)
    return {"X-Notification-Timestamp": ts, "X-Notification-Signature": digest}


class DevelopmentNotificationProvider(NotificationProvider):
    name = "development"

    behaviour: str = "ok"
    bad_destinations: set[str] = set()
    sent: dict[str, dict] = {}
    send_calls: list[str] = []

    def __init__(self, *, webhook_secret: str | None, tolerance_seconds: int):
        self._secret = webhook_secret
        self._tolerance = tolerance_seconds

    @classmethod
    def reset(cls) -> None:
        cls.behaviour = "ok"
        cls.bad_destinations = set()
        cls.sent = {}
        cls.send_calls = []

    @staticmethod
    def ref_for(key: str) -> str:
        return "dev-msg-" + hashlib.sha256(key.encode()).hexdigest()[:24]

    async def send(self, *, channel, destination, body, subject, idempotency_key) -> SendResult:
        self.send_calls.append(idempotency_key)
        if self.behaviour == "transient":
            raise NotificationTransient("provider unavailable")
        if self.behaviour == "permanent" or (
            self.behaviour == "permanent_for" and destination in self.bad_destinations
        ):
            raise NotificationPermanent("rejected", code="INVALID_DESTINATION")
        if idempotency_key not in self.sent:  # exactly one message per key
            self.sent[idempotency_key] = {
                "provider_ref": self.ref_for(idempotency_key),
                "channel": channel,
                "destination": destination,
                "body": body,
                "subject": subject,
            }
        if self.behaviour == "timeout_after":
            raise NotificationTransient("timed out after accepting")
        return SendResult(provider_ref=self.sent[idempotency_key]["provider_ref"])

    def verify_webhook(self, *, headers, body: bytes) -> DeliveryReceipt:
        try:
            webhook_signature.verify(
                secret=self._secret, headers=headers, body=body,
                timestamp_header=TIMESTAMP_HEADER, signature_header=SIGNATURE_HEADER,
                tolerance_seconds=self._tolerance,
            )
        except webhook_signature.SignatureError as exc:
            raise NotificationSignatureInvalid(str(exc)) from exc
        try:
            data = json.loads(body)
            event_id, ref = str(data["event_id"]), str(data["provider_ref"])
            status = str(data["status"]).upper()
            occurred = datetime.fromisoformat(data["occurred_at"]) if data.get("occurred_at") else None
        except (ValueError, KeyError, TypeError) as exc:
            raise NotificationCallbackMalformed("unusable callback body") from exc
        if status not in {"DELIVERED", "FAILED"} or not event_id or not ref:
            raise NotificationCallbackMalformed("unusable callback body")
        return DeliveryReceipt(event_id, ref, status, occurred, data.get("failure_code") or None)
