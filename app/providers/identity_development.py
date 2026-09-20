import hashlib

from app.providers.identity_verification import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    IdentityVerificationSession,
)


class DevelopmentIdentityVerificationProvider(IdentityVerificationProvider):
    """Development adapter only; never represents a real liveness decision."""

    async def start_session(self, user_id: str) -> IdentityVerificationSession:
        ref = hashlib.sha256(user_id.encode()).hexdigest()[:24]
        return IdentityVerificationSession(
            provider_ref=f"dev-identity-{ref}",
            capture_session_token=f"dev-capture-{ref}",
        )

    async def submit_capture(
        self,
        provider_ref: str,
        capture_ref: str,
    ) -> IdentityVerificationResult:
        return IdentityVerificationResult(status="PROCESSING")
