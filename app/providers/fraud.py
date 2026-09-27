from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.fraud import FraudAssessmentResult


class FraudProvider(ABC):
    @abstractmethod
    async def assess_fraud(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
    ) -> FraudAssessmentResult:
        raise NotImplementedError