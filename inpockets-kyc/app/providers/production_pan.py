from app.providers.pan import PANProvider, PANVerificationResult


class ProductionPANProvider(PANProvider):
    async def verify(
        self,
        pan_number: str,
        full_name: str,
    ) -> PANVerificationResult:
        raise NotImplementedError(
            "Production PAN provider is not configured yet."
        )
