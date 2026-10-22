"""Shared HMAC-SHA256 webhook verification: signature over "<timestamp>.<body>"."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping


class SignatureError(Exception):
    pass


def sign(secret: str, body: bytes, timestamp: int | None = None) -> tuple[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return ts, digest


def verify(
    *,
    secret: str | None,
    headers: Mapping[str, str],
    body: bytes,
    timestamp_header: str,
    signature_header: str,
    tolerance_seconds: int,
) -> None:
    """Raise SignatureError unless the callback is authentic and fresh.

    Fails closed when no secret is configured.
    """
    if not secret:
        raise SignatureError("webhook secret not configured")
    lowered = {k.lower(): v for k, v in headers.items()}
    ts, sig = lowered.get(timestamp_header), lowered.get(signature_header)
    if not ts or not sig:
        raise SignatureError("missing signature headers")
    try:
        ts_int = int(ts)
    except ValueError as exc:
        raise SignatureError("bad timestamp") from exc
    if abs(time.time() - ts_int) > tolerance_seconds:
        raise SignatureError("timestamp outside tolerance")
    _, expected = sign(secret, body, ts_int)
    if not hmac.compare_digest(expected, sig):
        raise SignatureError("signature mismatch")
