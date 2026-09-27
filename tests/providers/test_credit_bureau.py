from uuid import uuid4

import pytest

from app.domain.credit import CreditAssessmentStatus, CreditScoreType
from app.providers.credit_bureau_development import (
    DevelopmentCreditBureauProvider,
)


@pytest.mark.asyncio
async def test_development_credit_bureau_returns_credit_assessment():
    provider = DevelopmentCreditBureauProvider()

    application_id = uuid4()
    result = await provider.assess_credit(
        user_id=uuid4(),
        application_id=application_id,
        consent_reference="consent-123",
    )

    assert result.provider == "development"
    assert result.provider_reference == f"dev-credit-{application_id}"
    assert result.status == CreditAssessmentStatus.COMPLETED

    assert result.report is not None
    assert result.report.score == 700
    assert result.report.score_type == CreditScoreType.BUREAU
    assert result.report.delinquent_accounts == 0


@pytest.mark.asyncio
async def test_development_credit_bureau_is_deterministic():
    provider = DevelopmentCreditBureauProvider()

    application_id = uuid4()

    first = await provider.assess_credit(
        user_id=uuid4(),
        application_id=application_id,
        consent_reference="consent-123",
    )

    second = await provider.assess_credit(
        user_id=uuid4(),
        application_id=application_id,
        consent_reference="consent-456",
    )

    assert first.provider_reference == second.provider_reference
    assert first.report is not None
    assert second.report is not None
    assert first.report.score == second.report.score