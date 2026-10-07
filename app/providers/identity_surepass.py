"""
Surepass liveness (identity verification) provider.

CONFIRM AGAINST YOUR SUREPASS SANDBOX DOCS before going live — see the
same caveat in pan_surepass.py.

IMPORTANT — this changes what the Flutter app must send as `capture_ref`:
Surepass's liveness product (per their public docs) takes an image
directly and returns a result synchronously — there's no vendor-side
"create a session, capture later" step. This provider's start_session()
only exists to satisfy the shared IdentityVerificationProvider interface
(every provider implements the same two methods); the real work happens
in submit_capture(), which expects `capture_ref` to actually BE the
selfie image — base64-encoded, optionally as a data URL
("data:image/jpeg;base64,...") — not the placeholder string the app
currently generates. See identity_verification_screen.dart's
`_submitCapture` — swap the placeholder for
`base64Encode(await image.readAsBytes())` once this provider is wired in.

Also note: because this is synchronous, `submit_capture` can return
VERIFIED/FAILED immediately — unlike the development stub, which always
returns PROCESSING and can never move past it.
"""

from __future__ import annotations

import base64
import hashlib

import httpx

from app.core.config import settings
from app.providers.identity_verification import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    IdentityVerificationSession,
)

# CONFIRM: exact path/product name — Surepass has separate "liveness" and
# "face-match" products; check whether you want one call or both chained.
LIVENESS_PATH = "/face/face-liveness"


class SurepassIdentityVerificationProvider(IdentityVerificationProvider):
    def _require_settings(self) -> str:
        if not settings.surepass_api_token:
            raise RuntimeError("SUREPASS_API_TOKEN is not configured")
        return settings.surepass_api_token

    async def start_session(self, user_id: str) -> IdentityVerificationSession:
        ref = hashlib.sha256(user_id.encode()).hexdigest()[:24]
        return IdentityVerificationSession(
            provider_ref=f"surepass-identity-{ref}",
            capture_session_token=f"surepass-capture-{ref}",
        )

    async def submit_capture(
        self,
        provider_ref: str,
        capture_ref: str,
    ) -> IdentityVerificationResult:
        api_token = self._require_settings()
        url = f"{settings.surepass_base_url}{LIVENESS_PATH}"

        try:
            image_b64 = _strip_data_url_prefix(capture_ref)
            base64.b64decode(image_b64, validate=True)
        except Exception as exc:
            raise RuntimeError(
                "capture_ref is not a valid base64-encoded image"
            ) from exc

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                # CONFIRM: field name for the image payload.
                json={"image": image_b64},
            )

        if response.is_error:
            raise RuntimeError(
                f"Surepass liveness provider failed with HTTP {response.status_code}: "
                f"{response.text}"
            )

        payload = response.json()
        data = payload.get("data", payload)

        confidence = data.get("confidence") or data.get("live_confidence")
        confidence_score = float(confidence) if confidence is not None else None
        is_live = bool(data.get("live", data.get("is_live", False)))

        if not is_live:
            return IdentityVerificationResult(
                status="FAILED",
                confidence_score=confidence_score,
                failure_reason=data.get("message") or "Liveness check failed",
            )

        return IdentityVerificationResult(
            status="VERIFIED",
            confidence_score=confidence_score,
        )


def _strip_data_url_prefix(value: str) -> str:
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value
