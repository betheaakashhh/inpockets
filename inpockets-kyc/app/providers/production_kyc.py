from app.providers.kyc import (
    KYCDocumentContent,
    KYCInitiationResult,
    KYCProvider,
    KYCStatusResult,
)


class ProductionKYCProvider(KYCProvider):
    async def initiate(
        self,
        user_id: str,
        consent_ref: str,
    ) -> KYCInitiationResult:
        raise NotImplementedError("Production KYC provider is not configured yet.")

    async def get_status(
        self,
        provider_ref: str,
    ) -> KYCStatusResult:
        raise NotImplementedError("Production KYC provider is not configured yet.")

    async def fetch_document(
        self,
        provider_document_ref: str,
    ) -> KYCDocumentContent:
        raise NotImplementedError("Production KYC provider is not configured yet.")
