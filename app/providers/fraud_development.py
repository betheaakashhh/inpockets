from uuid import UUID

from app.domain.fraud import (
    FraudAssessmentResult,
    FraudAssessmentStatus,
    FraudRiskLevel,
)
from app.providers.fraud import FraudProvider


class DevelopmentFraudProvider(FraudProvider):
    async def assess_fraud(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
    ) -> FraudAssessmentResult:
        return FraudAssessmentResult(
            provider="development",
            provider_reference=f"dev-fraud-{application_id}",
            status=FraudAssessmentStatus.COMPLETED,
            risk_level=FraudRiskLevel.LOW,
        )