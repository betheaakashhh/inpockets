from app.providers.identity_verification import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    IdentityVerificationSession,
)


class ProductionIdentityVerificationProvider(IdentityVerificationProvider):
    async def start_session(
        self,
        user_id: str,
    ) -> IdentityVerificationSession:
        raise NotImplementedError(
            "Production identity verification provider is not configured yet."
        )

    async def submit_capture(
        self,
        provider_ref: str,
        capture_ref: str,
    ) -> IdentityVerificationResult:
        raise NotImplementedError(
            "Production identity verification provider is not configured yet."
        )
