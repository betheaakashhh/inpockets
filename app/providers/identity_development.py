import hashlib

from app.core.config import get_settings

from app.providers.identity_verification import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    IdentityVerificationSession,
)


class DevelopmentIdentityVerificationProvider(IdentityVerificationProvider):
    """Development adapter only; never represents a real liveness decision."""

    def _result(self) -> str:
        result = get_settings().dev_identity_result.upper()
        if get_settings().environment.lower() not in {"development", "test"}:
            raise RuntimeError("Development identity provider is only available in development/test environments")
        if result not in {"PENDING", "PROCESSING", "VERIFIED", "FAILED", "RETRY_REQUIRED"}:
            raise RuntimeError(f"Unsupported development identity result: {result}")
        return result

    async def start_session(self, user_id: str) -> IdentityVerificationSession:
        self._result()
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
        return IdentityVerificationResult(status="VERIFIED")



# for production identity provider, the submit_capture method would typically involve sending the captured data to the provider's API and receiving a response indicating the result of the identity verification process. In this development implementation, it simply returns a predetermined result based on the configuration.

#   async def submit_capture(
#         self,
#         provider_ref: str,
#         capture_ref: str,
#     ) -> IdentityVerificationResult:
#         return IdentityVerificationResult(status=self._result())