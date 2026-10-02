import hashlib

from app.core.config import get_settings

from app.providers.kyc import KYCInitiationResult, KYCProvider, KYCStatusResult


class DevelopmentKYCProvider(KYCProvider):
    """Development adapter only; no real KYC provider is contacted."""

    def _result(self) -> str:
        result = get_settings().dev_kyc_result.upper()
        if get_settings().environment.lower() not in {"development", "test"}:
            raise RuntimeError("Development KYC provider is only available in development/test environments")
        if result not in {"PENDING", "PROCESSING", "VERIFIED", "FAILED"}:
            raise RuntimeError(f"Unsupported development KYC result: {result}")
        return result

    async def initiate(self, user_id: str, consent_ref: str) -> KYCInitiationResult:
        ref = hashlib.sha256(f"{user_id}:{consent_ref}".encode()).hexdigest()[:24]
        result = self._result()
        return KYCInitiationResult(
            provider_ref=f"dev-kyc-{ref}",
            consent_url=None if result == "VERIFIED" else None,
        )

    async def get_status(self, provider_ref: str) -> KYCStatusResult:
        return KYCStatusResult(status=self._result())

    async def fetch_document(self, provider_document_ref: str):
        raise NotImplementedError("Development KYC provider does not provide documents")
