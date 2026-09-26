from uuid import UUID

from app.domain.credit import (
    CreditAssessmentResult,
    CreditAssessmentStatus,
    CreditReport,
    CreditScoreType,
)
from app.providers.credit_bureau import CreditBureauProvider


class DevelopmentCreditBureauProvider(CreditBureauProvider):
    """Deterministic development provider.

    This provider must never be used as a production credit bureau.
    """

    async def assess_credit(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
        consent_reference: str,
    ) -> CreditAssessmentResult:
        provider_reference = f"dev-credit-{application_id}"

        return CreditAssessmentResult(
            provider="development",
            provider_reference=provider_reference,
            status=CreditAssessmentStatus.COMPLETED,
            report=CreditReport(
                provider="development",
                provider_reference=provider_reference,
                score=700,
                score_type=CreditScoreType.BUREAU,
                total_accounts=2,
                active_accounts=1,
                delinquent_accounts=0,
                recent_inquiries=0,
            ),
        )