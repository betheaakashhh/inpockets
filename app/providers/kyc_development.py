import hashlib

from app.providers.kyc import KYCInitiationResult, KYCProvider, KYCStatusResult


class DevelopmentKYCProvider(KYCProvider):
    """Development adapter only; no real KYC provider is contacted."""

    async def initiate(self, user_id: str, consent_ref: str) -> KYCInitiationResult:
        ref = hashlib.sha256(f"{user_id}:{consent_ref}".encode()).hexdigest()[:24]
        return KYCInitiationResult(
            provider_ref=f"dev-kyc-{ref}",
            consent_url=f"https://example.invalid/kyc/{ref}",
        )

    async def get_status(self, provider_ref: str) -> KYCStatusResult:
        return KYCStatusResult(status="PENDING")

    async def fetch_document(self, provider_document_ref: str):
        raise NotImplementedError("Development KYC provider does not provide documents")
