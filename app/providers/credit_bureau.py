from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.credit import CreditAssessmentResult


class CreditBureauProvider(ABC):
    """Provider-neutral interface for obtaining credit bureau assessments."""

    @abstractmethod
    async def assess_credit(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
        consent_reference: str,
    ) -> CreditAssessmentResult:
        """Request a credit assessment for a loan application."""
        raise NotImplementedError