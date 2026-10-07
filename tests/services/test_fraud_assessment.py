from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
import asyncio
import pytest

from app.domain.fraud import (
    FraudAssessmentResult,
    FraudAssessmentStatus,
    FraudRiskLevel,
    FraudSignal,
)
from app.models.fraud_assessment import FraudAssessment
from app.providers.fraud import FraudProvider
from app.repositories.fraud_assessment import FraudAssessmentRepository
from app.repositories.loan_application import LoanApplicationRepository
from app.services.fraud_assessment import FraudAssessmentService


async def create_test_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)

    return await repository.create(
        application_number=f"INP-FRAUD-{uuid4().hex[:12]}",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )


class FakeFraudProvider(FraudProvider):
    def __init__(self, result: FraudAssessmentResult):
        self.result = result
        self.calls = 0

    async def assess_fraud(
        self,
        *,
        user_id,
        application_id,
    ):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_assess_persists_completed_result(db_session, user):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    provider = FakeFraudProvider(
        FraudAssessmentResult(
            provider="development",
            provider_reference=f"fraud-{uuid4()}",
            status=FraudAssessmentStatus.COMPLETED,
            risk_level=FraudRiskLevel.LOW,
            signals=(
                FraudSignal(
                    code="DEVICE_CHECK",
                    description="Device check passed",
                    severity="LOW",
                ),
            ),
        )
    )

    repository = FraudAssessmentRepository(db_session)
    service = FraudAssessmentService(repository, provider)

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
    )

    assert assessment.id is not None
    assert assessment.loan_application_id == application.id
    assert assessment.user_id == user.id
    assert assessment.provider == "development"
    assert assessment.status == "COMPLETED"
    assert assessment.risk_level == "LOW"
    assert assessment.signals == [
        {
            "code": "DEVICE_CHECK",
            "description": "Device check passed",
            "severity": "LOW",
        }
    ]
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_assess_reuses_existing_completed_assessment(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    existing = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        provider="development",
        provider_reference=f"fraud-{uuid4()}",
        status=FraudAssessmentStatus.COMPLETED,
        risk_level=FraudRiskLevel.LOW,
        signals=[],
        requested_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )

    await db_session.commit()

    provider = FakeFraudProvider(
        FraudAssessmentResult(
            provider="should-not-be-called",
            provider_reference="should-not-be-called",
            status=FraudAssessmentStatus.COMPLETED,
            risk_level=FraudRiskLevel.HIGH,
        )
    )

    service = FraudAssessmentService(repository, provider)

    result = await service.assess(
        user_id=user.id,
        application_id=application.id,
    )

    assert result.id == existing.id
    assert result.risk_level == "LOW"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_assess_persists_provider_failure(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    provider = FakeFraudProvider(
        FraudAssessmentResult(
            provider="development",
            provider_reference=f"fraud-{uuid4()}",
            status=FraudAssessmentStatus.FAILED,
            risk_level=FraudRiskLevel.UNKNOWN,
            failure_reason="Provider timeout",
        )
    )

    repository = FraudAssessmentRepository(db_session)
    service = FraudAssessmentService(repository, provider)

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
    )

    assert assessment.status == "FAILED"
    assert assessment.risk_level == "UNKNOWN"
    assert assessment.failure_reason == "Provider timeout"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_assess_preserves_multiple_fraud_signals(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    provider = FakeFraudProvider(
        FraudAssessmentResult(
            provider="development",
            provider_reference=f"fraud-{uuid4()}",
            status=FraudAssessmentStatus.COMPLETED,
            risk_level=FraudRiskLevel.MEDIUM,
            signals=(
                FraudSignal(
                    code="DEVICE_CHECK",
                    description="Device signal requires review",
                    severity="MEDIUM",
                ),
                FraudSignal(
                    code="VELOCITY_CHECK",
                    description="Application velocity flag",
                    severity="HIGH",
                ),
            ),
        )
    )

    repository = FraudAssessmentRepository(db_session)
    service = FraudAssessmentService(repository, provider)

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
    )

    assert assessment.risk_level == "MEDIUM"
    assert assessment.signals == [
        {
            "code": "DEVICE_CHECK",
            "description": "Device signal requires review",
            "severity": "MEDIUM",
        },
        {
            "code": "VELOCITY_CHECK",
            "description": "Application velocity flag",
            "severity": "HIGH",
        },
    ]


@pytest.mark.asyncio
async def test_failed_previous_assessment_does_not_block_retry(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        provider="development",
        provider_reference=f"fraud-failed-{uuid4()}",
        status=FraudAssessmentStatus.FAILED,
        risk_level=FraudRiskLevel.UNKNOWN,
        failure_reason="Temporary provider failure",
        requested_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )

    await db_session.commit()

    provider = FakeFraudProvider(
        FraudAssessmentResult(
            provider="development",
            provider_reference=f"fraud-success-{uuid4()}",
            status=FraudAssessmentStatus.COMPLETED,
            risk_level=FraudRiskLevel.LOW,
        )
    )

    service = FraudAssessmentService(repository, provider)

    result = await service.assess(
        user_id=user.id,
        application_id=application.id,
    )

    assert result.status == "COMPLETED"
    assert result.risk_level == "LOW"
    assert provider.calls == 1

    history = await repository.list_by_loan_application(
        application.id
    )

    assert len(history) == 2
@pytest.mark.asyncio
async def test_provider_timeout_is_persisted_as_failed_assessment(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    class TimeoutProvider(FraudProvider):
        async def assess_fraud(
            self,
            *,
            user_id,
            application_id,
        ):
            raise asyncio.TimeoutError

    repository = FraudAssessmentRepository(db_session)
    service = FraudAssessmentService(
        repository,
        TimeoutProvider(),
    )

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
    )

    assert assessment.status == "FAILED"
    assert assessment.risk_level == "UNKNOWN"
    assert assessment.failure_reason == "fraud provider timeout"

    history = await repository.list_by_loan_application(
        application.id
    )

    assert len(history) == 1