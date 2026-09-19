import uuid

from app.providers.kyc import (
    KYCDocumentContent,
    KYCInitiationResult,
    KYCProvider,
    KYCStatusResult,
)


class MockKYCProvider(KYCProvider):
    async def initiate(
        self,
        user_id: str,
        consent_ref: str,
    ) -> KYCInitiationResult:
        ref = f"mock_kyc_{uuid.uuid4().hex[:12]}"
        return KYCInitiationResult(
            provider_ref=ref,
            consent_url=f"https://sandbox.digilocker.example/consent/{ref}",
        )

    async def get_status(
        self,
        provider_ref: str,
    ) -> KYCStatusResult:
        return KYCStatusResult(
            status="verified",
            available_document_refs=(f"{provider_ref}_doc_1",),
        )

    async def fetch_document(
        self,
        provider_document_ref: str,
    ) -> KYCDocumentContent:
        # A tiny valid 1x1 PNG, standing in for a real retrieved KYC document.
        fake_png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
            "53de0000000c4944415478da6360606060000000050001a5f645400000000049454e44ae426082"
        )
        return KYCDocumentContent(
            provider_document_ref=provider_document_ref,
            document_type="photo_id",
            content=fake_png,
            content_type="image/png",
        )
