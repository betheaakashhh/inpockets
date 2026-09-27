from uuid import uuid4

import pytest

from app.domain.fraud import (
    FraudAssessmentStatus,
    FraudRiskLevel,
)
from app.providers.fraud_development import DevelopmentFraudProvider


@pytest.mark.asyncio
async def test_development_fraud_provider_returns_completed_result():
    provider = DevelopmentFraudProvider()

    user_id = uuid4()
    application_id = uuid4()

    result = await provider.assess_fraud(
        user_id=user_id,
        application_id=application_id,
    )

    assert result.provider == "development"
    assert result.provider_reference == f"dev-fraud-{application_id}"
    assert result.status == FraudAssessmentStatus.COMPLETED
    assert result.risk_level == FraudRiskLevel.LOW
    assert result.signals == ()
    assert result.failure_reason is None