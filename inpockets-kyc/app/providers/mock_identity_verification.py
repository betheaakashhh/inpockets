"""
Note on architecture: this mock (and the real provider that eventually
replaces it) is not given raw photo/video bytes directly by our backend.
Most liveness vendors capture and upload client-side through their own SDK,
handing back only a reference - so `submit_capture` takes a `capture_ref`
or reference, not bytes. If the eventual vendor works differently, only
this file and its production counterpart need to change.
"""

import uuid

from app.providers.identity_verification import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    IdentityVerificationSession,
)


class MockIdentityVerificationProvider(IdentityVerificationProvider):
    async def start_session(
        self,
        user_id: str,
    ) -> IdentityVerificationSession:
        ref = f"mock_idv_{uuid.uuid4().hex[:12]}"
        return IdentityVerificationSession(
            provider_ref=ref,
            capture_session_token=f"tok_{ref}",
        )

    async def submit_capture(
        self,
        provider_ref: str,
        capture_ref: str,
    ) -> IdentityVerificationResult:
        return IdentityVerificationResult(
            status="verified",
            confidence_score=0.97,
        )
