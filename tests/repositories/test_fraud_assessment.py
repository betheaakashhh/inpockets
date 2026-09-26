from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.fraud_assessment import FraudAssessment
from app.repositories.fraud_assessment import FraudAssessmentRepository
from app.repositories.loan_application import LoanApplicationRepository


async def create_test_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)

    return await repository.create(
        application_number=f"INP-FRAUD-{uuid4().hex[:12]}",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )


@pytest.mark.asyncio
async def test_create_fraud_assessment(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    assessment = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
        provider="development",
        provider_reference=f"dev-fraud-{uuid4()}",
        status="COMPLETED",
        risk_level="LOW",
        signals=[
            {
                "code": "DEVICE_CHECK",
                "description": "Development fraud check passed",
                "severity": "LOW",
            }
        ],
        model_version="development-v1",
        requested_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )

    assert assessment.id is not None
    assert assessment.loan_application_id == loan_application.id
    assert assessment.user_id == user.id
    assert assessment.provider == "development"
    assert assessment.status == "COMPLETED"
    assert assessment.risk_level == "LOW"
    assert len(assessment.signals) == 1

    await db_session.commit()


@pytest.mark.asyncio
async def test_get_by_id(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    assessment = FraudAssessment(
        loan_application_id=loan_application.id,
        user_id=user.id,
        provider="development",
        provider_reference=f"dev-fraud-{uuid4()}",
        status="COMPLETED",
        risk_level="LOW",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(assessment)
    await db_session.commit()

    result = await repository.get_by_id(assessment.id)

    assert result is not None
    assert result.id == assessment.id


@pytest.mark.asyncio
async def test_get_by_provider_reference(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    provider_reference = f"dev-fraud-{uuid4()}"

    assessment = FraudAssessment(
        loan_application_id=loan_application.id,
        user_id=user.id,
        provider="development",
        provider_reference=provider_reference,
        status="COMPLETED",
        risk_level="LOW",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(assessment)
    await db_session.commit()

    result = await repository.get_by_provider_reference(
        provider="development",
        provider_reference=provider_reference,
    )

    assert result is not None
    assert result.id == assessment.id


@pytest.mark.asyncio
async def test_list_by_loan_application(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    for risk_level in ("LOW", "MEDIUM"):
        db_session.add(
            FraudAssessment(
                loan_application_id=loan_application.id,
                user_id=user.id,
                provider="development",
                provider_reference=f"dev-fraud-{uuid4()}",
                status="COMPLETED",
                risk_level=risk_level,
                requested_at=datetime.now(timezone.utc),
            )
        )

    await db_session.commit()

    results = await repository.list_by_loan_application(
        loan_application.id
    )

    assert len(results) == 2
    assert results[0].loan_application_id == loan_application.id
    assert results[1].loan_application_id == loan_application.id


@pytest.mark.asyncio
async def test_list_by_user(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    repository = FraudAssessmentRepository(db_session)

    db_session.add(
        FraudAssessment(
            loan_application_id=loan_application.id,
            user_id=user.id,
            provider="development",
            provider_reference=f"dev-fraud-{uuid4()}",
            status="COMPLETED",
            risk_level="LOW",
            requested_at=datetime.now(timezone.utc),
        )
    )

    await db_session.commit()

    results = await repository.list_by_user(user.id)

    assert len(results) == 1
    assert results[0].user_id == user.id