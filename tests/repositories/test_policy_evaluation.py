from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.loan_application import LoanApplication
from app.models.policy_evaluation import PolicyEvaluation
from app.models.user import User
from app.repositories.loan_application import LoanApplicationRepository
from app.repositories.policy_evaluation import (
    PolicyEvaluationRepository,
)
from app.repositories.policy_version import PolicyVersionRepository


async def create_test_user_and_application(db_session):
    user = User(
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    db_session.add(user)
    await db_session.flush()

    loan_application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:20].upper()}",
        user_id=user.id,
        requested_amount=Decimal("10000.00"),
        requested_tenure_days=30,
    )

    db_session.add(loan_application)
    await db_session.flush()

    return user, loan_application


async def create_test_policy_version(
    db_session,
    version="policy-v1",
):
    repository = PolicyVersionRepository(db_session)

    return await repository.create(
        version=version,
        effective_from=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_policy_evaluation(db_session):
    user, application = await create_test_user_and_application(
        db_session,
    )

    policy_version = await create_test_policy_version(
        db_session,
        "policy-v1",
    )

    repository = PolicyEvaluationRepository(db_session)

    evaluated_at = datetime.now(timezone.utc)

    evaluation = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_version.id,
        policy_version=policy_version.version,
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=[
            "REQUIRE_MANUAL_REVIEW",
        ],
        reasons=[
            "LENDER_ADMIN_REVIEW_REQUIRED",
        ],
        input_snapshot={
            "risk_band": "LOW",
            "requested_amount": "10000.00",
        },
        recommended_amount=Decimal("8000.00"),
        max_eligible_amount=Decimal("10000.00"),
        evaluated_at=evaluated_at,
    )

    assert evaluation.id is not None
    assert evaluation.loan_application_id == application.id
    assert evaluation.user_id == user.id
    assert evaluation.policy_version_id == policy_version.id
    assert evaluation.policy_version == "policy-v1"
    assert evaluation.decision_route == "MANUAL_REVIEW"
    assert evaluation.matched_rule_codes == [
        "REQUIRE_MANUAL_REVIEW",
    ]
    assert evaluation.reasons == [
        "LENDER_ADMIN_REVIEW_REQUIRED",
    ]

    await db_session.commit()


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    user, application = await create_test_user_and_application(
        db_session,
    )

    policy_version = await create_test_policy_version(
        db_session,
    )

    repository = PolicyEvaluationRepository(db_session)

    evaluation = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_version.id,
        policy_version="policy-v1",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["MANUAL_REVIEW"],
        reasons=["ADMIN_REVIEW_REQUIRED"],
        input_snapshot={"risk_band": "MEDIUM"},
        evaluated_at=datetime.now(timezone.utc),
    )

    result = await repository.get_by_id(evaluation.id)

    assert result is not None
    assert result.id == evaluation.id
    assert result.loan_application_id == application.id


@pytest.mark.asyncio
async def test_list_by_loan_application_preserves_history(
    db_session,
):
    user, application = await create_test_user_and_application(
        db_session,
    )

    policy_v1 = await create_test_policy_version(
        db_session,
        "policy-v1",
    )

    policy_v2 = await create_test_policy_version(
        db_session,
        "policy-v2",
    )

    repository = PolicyEvaluationRepository(db_session)

    first = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_v1.id,
        policy_version="policy-v1",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["RULE_V1"],
        reasons=["FIRST_EVALUATION"],
        input_snapshot={
            "risk_band": "LOW",
        },
        evaluated_at=datetime.now(timezone.utc),
    )

    second = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_v2.id,
        policy_version="policy-v2",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["RULE_V2"],
        reasons=["SECOND_EVALUATION"],
        input_snapshot={
            "risk_band": "MEDIUM",
        },
        evaluated_at=datetime.now(timezone.utc),
    )

    results = await repository.list_by_loan_application(
        application.id,
    )

    assert len(results) == 2
    assert results[0].id == first.id
    assert results[1].id == second.id

    assert results[0].policy_version == "policy-v1"
    assert results[1].policy_version == "policy-v2"


@pytest.mark.asyncio
async def test_list_by_user(db_session):
    user, application = await create_test_user_and_application(
        db_session,
    )

    policy_version = await create_test_policy_version(
        db_session,
    )

    repository = PolicyEvaluationRepository(db_session)

    await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_version.id,
        policy_version="policy-v1",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["MANUAL_REVIEW"],
        reasons=["ADMIN_REVIEW_REQUIRED"],
        input_snapshot={},
        evaluated_at=datetime.now(timezone.utc),
    )

    results = await repository.list_by_user(user.id)

    assert len(results) == 1
    assert results[0].user_id == user.id


@pytest.mark.asyncio
async def test_get_latest_for_loan_application(db_session):
    user, application = await create_test_user_and_application(
        db_session,
    )

    policy_v1 = await create_test_policy_version(
        db_session,
        "policy-v1",
    )

    policy_v2 = await create_test_policy_version(
        db_session,
        "policy-v2",
    )

    repository = PolicyEvaluationRepository(db_session)

    first = PolicyEvaluation(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_v1.id,
        policy_version="policy-v1",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["RULE_V1"],
        reasons=["FIRST"],
        input_snapshot={"version": "v1"},
        evaluated_at=datetime.now(timezone.utc),
    )

    db_session.add(first)
    await db_session.flush()

    second = PolicyEvaluation(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_v2.id,
        policy_version="policy-v2",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["RULE_V2"],
        reasons=["SECOND"],
        input_snapshot={"version": "v2"},
        evaluated_at=datetime.now(timezone.utc),
    )

    db_session.add(second)
    await db_session.flush()

    result = await repository.get_latest_for_loan_application(
        application.id,
    )

    assert result is not None
    assert result.id == second.id
    assert result.policy_version == "policy-v2"


@pytest.mark.asyncio
async def test_historical_evaluation_retains_policy_snapshot(
    db_session,
):
    user, application = await create_test_user_and_application(
        db_session,
    )

    policy_version = await create_test_policy_version(
        db_session,
        "policy-v1",
    )

    repository = PolicyEvaluationRepository(db_session)

    evaluation = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy_version.id,
        policy_version="policy-v1",
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=[
            "REQUIRE_MANUAL_REVIEW",
        ],
        reasons=[
            "ADMIN_REVIEW_REQUIRED",
        ],
        input_snapshot={
            "risk_score": "25.00",
            "risk_band": "LOW",
            "requested_amount": "10000.00",
        },
        evaluated_at=datetime.now(timezone.utc),
    )

    await db_session.commit()

    result = await repository.get_by_id(evaluation.id)

    assert result is not None
    assert result.policy_version == "policy-v1"
    assert result.input_snapshot == {
        "risk_score": "25.00",
        "risk_band": "LOW",
        "requested_amount": "10000.00",
    }
    assert result.matched_rule_codes == [
        "REQUIRE_MANUAL_REVIEW",
    ]
    assert result.reasons == [
        "ADMIN_REVIEW_REQUIRED",
    ]