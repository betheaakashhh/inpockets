from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.affordability_assessment import AffordabilityAssessment
from app.models.loan_application import LoanApplication
from app.models.user import User
from app.repositories.affordability_assessment import (
    AffordabilityAssessmentRepository,
)


async def create_user_and_application(db_session):
    user = User(
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    db_session.add(user)
    await db_session.flush()

    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:20].upper()}",
        user_id=user.id,
        requested_amount=Decimal("15000.00"),
        requested_tenure_days=30,
    )

    db_session.add(application)
    await db_session.flush()

    return user, application


@pytest.mark.asyncio
async def test_create_affordability_assessment(
    db_session,
):
    repository = AffordabilityAssessmentRepository(db_session)

    user, application = await create_user_and_application(db_session)

    assessment = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        source_type="CUSTOMER_DECLARED",
        source_reference="test-source",
        status="COMPLETED",
        monthly_income=Decimal("30000.00"),
        monthly_obligations=Decimal("8000.00"),
        requested_amount=Decimal("15000.00"),
        requested_tenure_days=30,
        disposable_monthly_income=Decimal("22000.00"),
        existing_obligation_ratio=Decimal("0.2667"),
        feature_snapshot={
            "monthly_income": "30000.00",
            "monthly_obligations": "8000.00",
        },
        calculation_version="v1",
        requested_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )

    assert assessment.id is not None
    assert assessment.loan_application_id == application.id
    assert assessment.user_id == user.id
    assert assessment.source_type == "CUSTOMER_DECLARED"
    assert assessment.status == "COMPLETED"
    assert assessment.monthly_income == Decimal("30000.00")
    assert assessment.monthly_obligations == Decimal("8000.00")
    assert assessment.disposable_monthly_income == Decimal("22000.00")
    assert assessment.calculation_version == "v1"


@pytest.mark.asyncio
async def test_get_by_id(
    db_session,
):
    repository = AffordabilityAssessmentRepository(db_session)

    user, application = await create_user_and_application(db_session)

    assessment = AffordabilityAssessment(
        loan_application_id=application.id,
        user_id=user.id,
        source_type="INTERNAL",
        source_reference="test-source",
        status="COMPLETED",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(assessment)
    await db_session.flush()

    result = await repository.get_by_id(assessment.id)

    assert result is not None
    assert result.id == assessment.id


@pytest.mark.asyncio
async def test_list_by_loan_application(
    db_session,
):
    repository = AffordabilityAssessmentRepository(db_session)

    user, application = await create_user_and_application(db_session)

    first = AffordabilityAssessment(
        loan_application_id=application.id,
        user_id=user.id,
        source_type="CUSTOMER_DECLARED",
        source_reference="first",
        status="COMPLETED",
        requested_at=datetime.now(timezone.utc),
    )

    second = AffordabilityAssessment(
        loan_application_id=application.id,
        user_id=user.id,
        source_type="VERIFIED_DATA",
        source_reference="second",
        status="COMPLETED",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add_all([first, second])
    await db_session.flush()

    results = await repository.list_by_loan_application(
        application.id
    )

    assert len(results) == 2
    assert {item.source_reference for item in results} == {
        "first",
        "second",
    }


@pytest.mark.asyncio
async def test_get_latest_for_loan_application(
    db_session,
):
    repository = AffordabilityAssessmentRepository(db_session)

    user, application = await create_user_and_application(db_session)

    first = AffordabilityAssessment(
        loan_application_id=application.id,
        user_id=user.id,
        source_type="CUSTOMER_DECLARED",
        source_reference="first",
        status="COMPLETED",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(first)
    await db_session.flush()

    second = AffordabilityAssessment(
        loan_application_id=application.id,
        user_id=user.id,
        source_type="VERIFIED_DATA",
        source_reference="second",
        status="COMPLETED",
        requested_at=datetime.now(timezone.utc),
    )

    db_session.add(second)
    await db_session.flush()

    result = await repository.get_latest_for_loan_application(
        application.id
    )

    assert result is not None
    assert result.id == second.id