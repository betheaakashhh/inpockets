from app.providers.pan import PANVerificationResult, PANProvider


class DevelopmentPANProvider(PANProvider):
    """Deterministic development adapter; never used as a production verifier."""

    async def verify(self, pan_number: str, full_name: str) -> PANVerificationResult:
        return PANVerificationResult(
            provider_ref=f"dev-pan-{pan_number[-4:]}",
            status="VERIFIED",
            verified_name=full_name,
            name_match_result="MATCH",
        )
