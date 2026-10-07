from decimal import Decimal
from uuid import uuid4
import asyncio
import pytest # type: ignore
from datetime import datetime, timezone

from app.domain.credit import (
    CreditAssessmentResult,
    CreditAssessmentStatus,
    CreditReport,
    CreditScoreType,
)
from app.models.credit_assessment import CreditAssessment
from app.repositories.credit_assessment import CreditAssessmentRepository
from app.repositories.loan_application import LoanApplicationRepository
from app.services.credit_assessment import CreditAssessmentService
from app.repositories.consent import ConsentRepository


class FakeCreditBureauProvider:
    def __init__(self, result: CreditAssessmentResult):
        self.result = result
        self.calls = 0

    async def assess_credit(
        self,
        *,
        user_id,
        application_id,
        consent_reference,
    ):
        self.calls += 1
        return self.result


async def create_test_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)

    return await repository.create(
        application_number=f"INP-CREDIT-{uuid4().hex[:12]}",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )

async def create_test_consent(db_session, user):
    repository = ConsentRepository(db_session)

    return await repository.create(
        user_id=user.id,
        consent_type="CREDIT_ASSESSMENT",
        version="1",
        status="GRANTED",
    )

@pytest.mark.asyncio
async def test_assess_persists_completed_credit_assessment(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    provider_reference = f"dev-credit-{uuid4()}"

    provider = FakeCreditBureauProvider(
        CreditAssessmentResult(
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
                total_outstanding=Decimal("15000.00"),
                recent_inquiries=0,
            ),
        )
    )

    repository = CreditAssessmentRepository(db_session)

    service = CreditAssessmentService(
        repository=repository,
        provider=provider,
    )
    consent = await create_test_consent(
        db_session,
        user,
    )

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
        consent_id=consent.id,
    )

    assert assessment.id is not None
    assert assessment.loan_application_id == application.id
    assert assessment.user_id == user.id
    assert assessment.provider == "development"
    assert assessment.provider_reference == provider_reference
    assert assessment.status == CreditAssessmentStatus.COMPLETED
    assert assessment.bureau_score == 700
    assert assessment.score_type == CreditScoreType.BUREAU
    assert assessment.total_accounts == 2
    assert assessment.active_accounts == 1
    assert assessment.delinquent_accounts == 0
    assert assessment.recent_inquiries == 0
    assert assessment.consent_id == consent.id

    await db_session.commit()


@pytest.mark.asyncio
async def test_assess_persists_failed_provider_result(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    provider = FakeCreditBureauProvider(
        CreditAssessmentResult(
            provider="development",
            provider_reference=f"dev-credit-{uuid4()}",
            status=CreditAssessmentStatus.FAILED,
            failure_reason="Provider unavailable",
        )
    )

    repository = CreditAssessmentRepository(db_session)

    service = CreditAssessmentService(
        repository=repository,
        provider=provider,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
        consent_id=consent.id,
    )

    assert assessment.status == CreditAssessmentStatus.FAILED
    assert assessment.failure_reason == "Provider unavailable"
    assert assessment.bureau_score is None

    await db_session.commit()


@pytest.mark.asyncio
async def test_assess_returns_existing_completed_assessment(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    repository = CreditAssessmentRepository(db_session)

    existing = CreditAssessment(
        loan_application_id=application.id,
        user_id=user.id,
        consent_id=consent.id,
        provider="development",
        provider_reference=f"dev-credit-{uuid4()}",
        status=CreditAssessmentStatus.COMPLETED,
        bureau_score=720,
        score_type=CreditScoreType.BUREAU,
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(existing)
    await db_session.commit()

    provider = FakeCreditBureauProvider(
        CreditAssessmentResult(
            provider="development",
            provider_reference=f"should-not-be-used-{uuid4()}",
            status=CreditAssessmentStatus.COMPLETED,
            report=CreditReport(
                provider="development",
                provider_reference="unused",
                score=700,
                score_type=CreditScoreType.BUREAU,
            ),
        )
    )

    service = CreditAssessmentService(
        repository=repository,
        provider=provider,
    )

    result = await service.assess(
        user_id=user.id,
        application_id=application.id,
        consent_id=consent.id,
    )

    assert result.id == existing.id
    assert result.bureau_score == 720
    assert result.consent_id == consent.id
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_assess_persists_processing_result(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    provider = FakeCreditBureauProvider(
        CreditAssessmentResult(
            provider="development",
            provider_reference=f"dev-credit-{uuid4()}",
            status=CreditAssessmentStatus.PROCESSING,
        )
    )

    repository = CreditAssessmentRepository(db_session)

    service = CreditAssessmentService(
        repository=repository,
        provider=provider,
    )
    
    consent = await create_test_consent(
        db_session,
        user,
    )

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
        consent_id=consent.id,
    )

    assert assessment.status == CreditAssessmentStatus.PROCESSING
    assert assessment.bureau_score is None

    await db_session.commit()

@pytest.mark.asyncio
async def test_provider_timeout_is_persisted_as_failed_assessment(
    db_session,
    user,
):
    application = await create_test_loan_application(
        db_session,
        user,
    )

    class TimeoutProvider:
        async def assess_credit(
            self,
            *,
            user_id,
            application_id,
            consent_reference,
        ):
            raise asyncio.TimeoutError

    repository = CreditAssessmentRepository(db_session)
    service = CreditAssessmentService(
        repository=repository,
        provider=TimeoutProvider(),
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    assessment = await service.assess(
        user_id=user.id,
        application_id=application.id,
        consent_id=consent.id,
    )

    assert assessment.status == CreditAssessmentStatus.FAILED
    assert assessment.bureau_score is None
    assert assessment.failure_reason == "credit provider timeout"

    history = await repository.list_by_loan_application(
        application.id
    )

    assert len(history) == 1
