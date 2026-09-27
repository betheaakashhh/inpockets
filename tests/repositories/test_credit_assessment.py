from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.credit_assessment import CreditAssessment
from app.repositories.consent import ConsentRepository
from app.repositories.credit_assessment import CreditAssessmentRepository
from app.repositories.loan_application import LoanApplicationRepository


async def create_test_consent(db_session, user):
    repository = ConsentRepository(db_session)

    return await repository.create(
        user_id=user.id,
        consent_type="CREDIT_ASSESSMENT",
        version="1",
        status="GRANTED",
    )


async def create_test_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)

    return await repository.create(
        application_number=f"INP-CREDIT-{uuid4().hex[:12]}",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("5000.00"),
        requested_tenure_days=30,
    )


@pytest.mark.asyncio
async def test_create_credit_assessment(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    repository = CreditAssessmentRepository(db_session)

    assessment = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
        consent_id=consent.id,
        provider="development",
        provider_reference=f"dev-credit-{loan_application.id}",
        status="COMPLETED",
        bureau_score=700,
        score_type="BUREAU",
        total_accounts=2,
        active_accounts=1,
        delinquent_accounts=0,
        total_outstanding=Decimal("15000.00"),
        recent_inquiries=0,
        feature_snapshot={
            "total_accounts": 2,
            "active_accounts": 1,
            "delinquent_accounts": 0,
        },
        provider_report_version="development-v1",
        requested_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )

    assert assessment.id is not None
    assert assessment.loan_application_id == loan_application.id
    assert assessment.user_id == user.id
    assert assessment.consent_id == consent.id
    assert assessment.provider == "development"
    assert assessment.bureau_score == 700

    await db_session.commit()


@pytest.mark.asyncio
async def test_get_by_id(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    repository = CreditAssessmentRepository(db_session)

    assessment = CreditAssessment(
        loan_application_id=loan_application.id,
        user_id=user.id,
        consent_id=consent.id,
        provider="development",
        provider_reference=f"dev-credit-{uuid4()}",
        status="COMPLETED",
        bureau_score=700,
        score_type="BUREAU",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(assessment)
    await db_session.commit()

    result = await repository.get_by_id(assessment.id)

    assert result is not None
    assert result.id == assessment.id
    assert result.consent_id == consent.id


@pytest.mark.asyncio
async def test_get_by_provider_reference(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    repository = CreditAssessmentRepository(db_session)

    provider_reference = f"dev-credit-{uuid4()}"

    assessment = CreditAssessment(
        loan_application_id=loan_application.id,
        user_id=user.id,
        consent_id=consent.id,
        provider="development",
        provider_reference=provider_reference,
        status="COMPLETED",
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
    assert result.consent_id == consent.id


@pytest.mark.asyncio
async def test_list_by_loan_application(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    repository = CreditAssessmentRepository(db_session)

    for index in range(2):
        db_session.add(
            CreditAssessment(
                loan_application_id=loan_application.id,
                user_id=user.id,
                consent_id=consent.id,
                provider="development",
                provider_reference=f"dev-credit-{uuid4()}",
                status="COMPLETED",
                bureau_score=700 + index,
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
    assert results[0].consent_id == consent.id
    assert results[1].consent_id == consent.id


@pytest.mark.asyncio
async def test_list_by_user(db_session, user):
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )

    consent = await create_test_consent(
        db_session,
        user,
    )

    repository = CreditAssessmentRepository(db_session)

    db_session.add(
        CreditAssessment(
            loan_application_id=loan_application.id,
            user_id=user.id,
            consent_id=consent.id,
            provider="development",
            provider_reference=f"dev-credit-{uuid4()}",
            status="COMPLETED",
            bureau_score=700,
            requested_at=datetime.now(timezone.utc),
        )
    )

    await db_session.commit()

    results = await repository.list_by_user(user.id)

    assert len(results) == 1
    assert results[0].user_id == user.id
    assert results[0].consent_id == consent.id