from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.risk_assessment import RiskAssessment
from app.repositories.loan_application import LoanApplicationRepository
from app.repositories.risk_assessment import RiskAssessmentRepository


async def create_test_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)

    return await repository.create(
        application_number=f"INP-RISK-{uuid4().hex[:12]}",
        user_id=user.id,
        status="DRAFT",
        requested_amount=Decimal("10000.00"),
        requested_tenure_days=30,
    )


def build_risk_assessment(application, user, **overrides):
    values = {
        "loan_application_id": application.id,
        "user_id": user.id,
        "model_version": "risk-v1",
        "status": "COMPLETED",
        "risk_score": Decimal("25.00"),
        "risk_band": "LOW",
        "recommended_action": "ASSESS",
        "recommended_amount": Decimal("8000.00"),
        "max_eligible_amount": Decimal("10000.00"),
        "factors": [
            {
                "code": "CREDIT_SCORE",
                "category": "CREDIT",
                "impact": "LOW",
            }
        ],
        "flags": [],
        "created_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return RiskAssessment(**values)


@pytest.mark.asyncio
async def test_create_risk_assessment(db_session, user):
    application = await create_test_loan_application(db_session, user)
    repository = RiskAssessmentRepository(db_session)

    assessment = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        model_version="risk-v1",
        status="COMPLETED",
        risk_score=Decimal("25.00"),
        risk_band="LOW",
        recommended_action="ASSESS",
        recommended_amount=Decimal("8000.00"),
        max_eligible_amount=Decimal("10000.00"),
        factors=[
            {
                "code": "CREDIT_SCORE",
                "category": "CREDIT",
                "impact": "LOW",
            }
        ],
        flags=[],
    )

    assert assessment.id is not None
    assert assessment.loan_application_id == application.id
    assert assessment.user_id == user.id
    assert assessment.model_version == "risk-v1"
    assert assessment.risk_score == Decimal("25.00")
    assert assessment.risk_band == "LOW"
    assert assessment.recommended_action == "ASSESS"
    assert assessment.max_eligible_amount == Decimal("10000.00")
    assert assessment.factors[0]["code"] == "CREDIT_SCORE"

    await db_session.commit()


@pytest.mark.asyncio
async def test_get_by_id(db_session, user):
    application = await create_test_loan_application(db_session, user)
    repository = RiskAssessmentRepository(db_session)

    assessment = build_risk_assessment(application, user)

    db_session.add(assessment)
    await db_session.commit()

    result = await repository.get_by_id(assessment.id)

    assert result is not None
    assert result.id == assessment.id
    assert result.loan_application_id == application.id


@pytest.mark.asyncio
async def test_list_by_loan_application_preserves_history(
    db_session,
    user,
):
    application = await create_test_loan_application(db_session, user)
    repository = RiskAssessmentRepository(db_session)

    first = build_risk_assessment(
        application,
        user,
        model_version="risk-v1",
        risk_score=Decimal("20.00"),
    )
    second = build_risk_assessment(
        application,
        user,
        model_version="risk-v2",
        risk_score=Decimal("35.00"),
        risk_band="MEDIUM",
    )

    db_session.add_all([first, second])
    await db_session.flush()

    results = await repository.list_by_loan_application(
        application.id
    )

    assert len(results) == 2
    assert [item.model_version for item in results] == [
        "risk-v1",
        "risk-v2",
    ]
    assert [item.risk_score for item in results] == [
        Decimal("20.00"),
        Decimal("35.00"),
    ]


@pytest.mark.asyncio
async def test_list_by_user(db_session, user):
    application = await create_test_loan_application(db_session, user)
    repository = RiskAssessmentRepository(db_session)

    assessment = build_risk_assessment(application, user)

    db_session.add(assessment)
    await db_session.commit()

    results = await repository.list_by_user(user.id)

    assert len(results) == 1
    assert results[0].user_id == user.id


@pytest.mark.asyncio
async def test_get_latest_for_loan_application(db_session, user):
    application = await create_test_loan_application(db_session, user)
    repository = RiskAssessmentRepository(db_session)

    first = build_risk_assessment(
        application,
        user,
        model_version="risk-v1",
    )
    db_session.add(first)
    await db_session.flush()

    second = build_risk_assessment(
        application,
        user,
        model_version="risk-v2",
    )
    db_session.add(second)
    await db_session.flush()

    result = await repository.get_latest_for_loan_application(
        application.id
    )

    assert result is not None
    assert result.id == second.id
    assert result.model_version == "risk-v2"
