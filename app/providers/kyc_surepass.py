"""
Surepass DigiLocker KYC provider.

CONFIRM AGAINST YOUR SUREPASS SANDBOX DOCS before going live — see the
same caveat in pan_surepass.py. The endpoint paths and field names below
follow the general shape every DigiLocker aggregator in this space uses
(initiate -> consent_url, poll status, fetch document by type), but the
literal strings need a final check against your own sandbox responses.

DESIGN NOTE — a real interface gap this file works around:
KYCProvider.fetch_document(provider_document_ref) only receives the
document-ref string; it has no way to also receive the DigiLocker
session/client_id needed to actually fetch a *specific user's* document.
Rather than changing the shared interface (which every provider,
including the development one, would then need updating for), this
provider encodes both pieces into the ref it hands back from
get_status()'s `available_document_refs`, as "{client_id}:{doc_type}",
and splits it back apart in fetch_document(). Self-contained; nothing
outside this file needs to change.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.providers.kyc import KYCDocumentContent, KYCInitiationResult, KYCProvider, KYCStatusResult

# CONFIRM: exact paths/params below.
DIGILOCKER_INITIALIZE_PATH = "/digilocker/initialize"
DIGILOCKER_STATUS_PATH = "/digilocker/status"
DIGILOCKER_DOCUMENT_PATH = "/digilocker/download-document/{doc_type}"

# Raw status strings this integration has seen documented across
# DigiLocker aggregators, mapped onto InPockets' own KYCStatus enum.
# CONFIRM the left-hand values against what Surepass actually returns.
_STATUS_MAP = {
    "PENDING": "PENDING",
    "INITIATED": "PENDING",
    "IN_PROGRESS": "PROCESSING",
    "AUTHENTICATED": "VERIFIED",
    "COMPLETED": "VERIFIED",
    "SUCCESS": "VERIFIED",
    "EXPIRED": "FAILED",
    "CONSENT_DENIED": "FAILED",
    "FAILED": "FAILED",
}


class SurepassKYCProvider(KYCProvider):
    def _require_settings(self) -> str:
        if not settings.surepass_api_token:
            raise RuntimeError("SUREPASS_API_TOKEN is not configured")
        return settings.surepass_api_token

    def _requested_document_types(self) -> list[str]:
        return [
            d.strip().upper()
            for d in settings.surepass_kyc_document_types.split(",")
            if d.strip()
        ]

    async def initiate(self, user_id: str, consent_ref: str) -> KYCInitiationResult:
        api_token = self._require_settings()
        if not settings.surepass_redirect_url:
            raise RuntimeError("SUREPASS_REDIRECT_URL is not configured")

        # Cashfree's equivalent field caps this at 50 chars, alphanumeric
        # plus . - _ ; Surepass's own limit isn't public, so this stays
        # conservative. CONFIRM the limit against your sandbox.
        verification_id = f"ip-{user_id}-{consent_ref}".replace("-", "")[:50]

        url = f"{settings.surepass_base_url}{DIGILOCKER_INITIALIZE_PATH}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "verification_id": verification_id,
                    "document_requested": self._requested_document_types(),
                    "redirect_url": settings.surepass_redirect_url,
                },
            )

        if response.is_error:
            raise RuntimeError(
                f"Surepass KYC initiate failed with HTTP {response.status_code}: "
                f"{response.text}"
            )

        payload = response.json()
        data = payload.get("data", payload)

        client_id = str(data.get("client_id") or verification_id)
        consent_url = data.get("url") or data.get("consent_url")
        if not consent_url:
            raise RuntimeError("Surepass response did not include a consent URL")

        return KYCInitiationResult(provider_ref=client_id, consent_url=consent_url)

    async def get_status(self, provider_ref: str) -> KYCStatusResult:
        api_token = self._require_settings()
        url = f"{settings.surepass_base_url}{DIGILOCKER_STATUS_PATH}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_token}"},
                # CONFIRM: param name — "verification_id" vs "client_id".
                params={"verification_id": provider_ref},
            )

        if response.is_error:
            raise RuntimeError(
                f"Surepass KYC status check failed with HTTP {response.status_code}: "
                f"{response.text}"
            )

        payload = response.json()
        data = payload.get("data", payload)
        raw_status = str(data.get("status", "")).upper()
        mapped_status = _STATUS_MAP.get(raw_status, "MANUAL_REVIEW")

        available_document_refs: tuple[str, ...] = ()
        if mapped_status == "VERIFIED":
            available_document_refs = tuple(
                f"{provider_ref}:{doc_type}"
                for doc_type in self._requested_document_types()
            )

        return KYCStatusResult(
            status=mapped_status,
            available_document_refs=available_document_refs,
            failure_reason=data.get("message") if mapped_status == "FAILED" else None,
        )

    async def fetch_document(self, provider_document_ref: str) -> KYCDocumentContent:
        api_token = self._require_settings()

        try:
            client_id, doc_type = provider_document_ref.split(":", 1)
        except ValueError as exc:
            raise RuntimeError(
                f"Malformed Surepass document ref: {provider_document_ref!r}"
            ) from exc

        path = DIGILOCKER_DOCUMENT_PATH.format(doc_type=doc_type.lower())
        url = f"{settings.surepass_base_url}{path}"

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_token}"},
                params={"verification_id": client_id},
            )

        if response.is_error:
            raise RuntimeError(
                f"Surepass document fetch failed with HTTP {response.status_code}: "
                f"{response.text}"
            )

        # CONFIRM: DigiLocker documents come back either as structured JSON
        # (masked Aadhaar demographic fields, say) or a base64-encoded file
        # (PDF/XML) depending on doc_type. This stores the raw response
        # body as-is — adjust if your sandbox wraps it in a "data"/"file"
        # field you need to unwrap and/or base64-decode first.
        content_type = response.headers.get("content-type", "application/json")

        return KYCDocumentContent(
            provider_document_ref=provider_document_ref,
            document_type=doc_type.upper(),
            content=response.content,
            content_type=content_type,
        )
