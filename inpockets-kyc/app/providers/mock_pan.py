import uuid

from app.providers.pan import PANProvider, PANVerificationResult


class MockPANProvider(PANProvider):
    async def verify(
        self,
        pan_number: str,
        full_name: str,
    ) -> PANVerificationResult:
        return PANVerificationResult(
            provider_ref=f"mock_pan_{uuid.uuid4().hex[:12]}",
            status="verified",
            verified_name=full_name,
            name_match_result="exact",
        )
