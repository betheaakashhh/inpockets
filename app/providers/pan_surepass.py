"""
Surepass PAN Comprehensive verification.

CONFIRM AGAINST YOUR SUREPASS SANDBOX DOCS before going live: the exact
endpoint path and the request/response field names below are this
integration's best-effort reconstruction from Surepass's publicly
documented product description and their published API base URL + auth
pattern (Bearer token, https://kyc-api.surepass.io/api/v1). Their full
request/response schema sits behind a developer-dashboard signup, so
every line marked `# CONFIRM` is a required check against your actual
sandbox response — not a verified fact.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.providers.pan import PANProvider, PANVerificationResult

# CONFIRM: Surepass groups PAN endpoints under /pan/*; "comprehensive" is
# the variant that also reports Aadhaar-linkage, not just format validity.
PAN_COMPREHENSIVE_PATH = "/pan/pan-comprehensive"


class SurepassPANProvider(PANProvider):
    def _require_settings(self) -> str:
        if not settings.surepass_api_token:
            raise RuntimeError("SUREPASS_API_TOKEN is not configured")
        return settings.surepass_api_token

    async def verify(self, pan_number: str, full_name: str) -> PANVerificationResult:
        api_token = self._require_settings()
        url = f"{settings.surepass_base_url}{PAN_COMPREHENSIVE_PATH}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                # CONFIRM: "id_number" is the field name Surepass uses on
                # several of their published verification endpoints.
                json={"id_number": pan_number},
            )

        if response.is_error:
            raise RuntimeError(
                f"Surepass PAN provider failed with HTTP {response.status_code}: "
                f"{response.text}"
            )

        payload = response.json()
        # CONFIRM: Surepass wraps results under a top-level "data" key on
        # most endpoints — adjust if your sandbox response differs.
        data = payload.get("data", payload)

        provider_ref = str(
            data.get("client_id") or data.get("reference_id") or pan_number
        )
        is_valid = bool(data.get("pan_valid", data.get("valid", True)))

        if not is_valid:
            return PANVerificationResult(
                provider_ref=provider_ref,
                status="FAILED",
                failure_reason=data.get("message") or "PAN could not be verified",
            )

        registered_name = data.get("full_name") or data.get("registered_name")
        name_match = _names_match(full_name, registered_name)

        return PANVerificationResult(
            provider_ref=provider_ref,
            status="VERIFIED" if name_match else "MANUAL_REVIEW",
            verified_name=registered_name,
            name_match_result="MATCH" if name_match else "MISMATCH",
            failure_reason=(
                None if name_match else "Registered name does not match profile name"
            ),
        )


def _names_match(profile_name: str, registered_name: str | None) -> bool:
    if not registered_name:
        return False
    return _normalize(profile_name) == _normalize(registered_name)


def _normalize(value: str) -> str:
    return " ".join(value.strip().upper().split())
