from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.loan_application import (
    LoanApplication,
    LoanApplicationStatus,
)
from app.repositories.loan_decision import LoanDecisionRepository


@pytest.mark.asyncio
async def test_create_and_get_by_id(db_session, user):
    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status=LoanApplicationStatus.DRAFT,
        requested_amount=5000,
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    from app.models.policy_version import PolicyVersion
    from app.models.policy_rule import PolicyRule
    from app.models.policy_evaluation import PolicyEvaluation

    policy = PolicyVersion(
        version=f"policy-{uuid4().hex[:8]}",
        effective_from=datetime.now(timezone.utc),
    )
    db_session.add(policy)
    await db_session.flush()

    rule = PolicyRule(
        policy_version_id=policy.id,
        code="MANUAL_REVIEW",
        rule_order=1,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={},
    )
    db_session.add(rule)
    await db_session.flush()

    evaluation = PolicyEvaluation(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy.id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["MANUAL_REVIEW"],
        reasons=["Manual review required."],
        input_snapshot={"risk_band": "MEDIUM"},
        evaluated_at=datetime.now(timezone.utc),
    )
    db_session.add(evaluation)
    await db_session.flush()

    repository = LoanDecisionRepository(db_session)

    decision = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_evaluation_id=evaluation.id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        reason_codes=["MANUAL_REVIEW_REQUIRED"],
        reasons=["Lender admin review is required."],
        input_snapshot={"risk_band": "MEDIUM"},
        decided_at=datetime.now(timezone.utc),
    )

    loaded = await repository.get_by_id(decision.id)

    assert loaded is not None
    assert loaded.id == decision.id
    assert loaded.policy_version == policy.version
    assert loaded.decision_route == "MANUAL_REVIEW"
    assert loaded.reason_codes == ["MANUAL_REVIEW_REQUIRED"]


@pytest.mark.asyncio
async def test_list_by_loan_application_preserves_history(
    db_session,
    user,
):
    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status=LoanApplicationStatus.DRAFT,
        requested_amount=5000,
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    from app.models.policy_version import PolicyVersion
    from app.models.policy_rule import PolicyRule
    from app.models.policy_evaluation import PolicyEvaluation

    policy = PolicyVersion(
        version=f"policy-{uuid4().hex[:8]}",
        effective_from=datetime.now(timezone.utc),
    )
    db_session.add(policy)
    await db_session.flush()

    rule = PolicyRule(
        policy_version_id=policy.id,
        code="MANUAL_REVIEW",
        rule_order=1,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={},
    )
    db_session.add(rule)
    await db_session.flush()

    repository = LoanDecisionRepository(db_session)

    first_evaluation = PolicyEvaluation(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy.id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["MANUAL_REVIEW"],
        reasons=["Initial review."],
        input_snapshot={"risk_band": "MEDIUM"},
        evaluated_at=datetime.now(timezone.utc),
    )
    db_session.add(first_evaluation)
    await db_session.flush()

    second_evaluation = PolicyEvaluation(
        loan_application_id=application.id,
        user_id=user.id,
        policy_version_id=policy.id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        matched_rule_codes=["MANUAL_REVIEW"],
        reasons=["Second evaluation."],
        input_snapshot={"risk_band": "LOW"},
        evaluated_at=datetime.now(timezone.utc),
    )
    db_session.add(second_evaluation)
    await db_session.flush()

    first = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_evaluation_id=first_evaluation.id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        reason_codes=["MANUAL_REVIEW_REQUIRED"],
        reasons=["Initial review."],
        input_snapshot={"risk_band": "MEDIUM"},
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    second = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_evaluation_id=second_evaluation.id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        reason_codes=["MANUAL_REVIEW_REQUIRED"],
        reasons=["Second review."],
        input_snapshot={"risk_band": "LOW"},
        decided_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    decisions = await repository.list_by_loan_application(
        application.id
    )

    assert [item.id for item in decisions] == [
        first.id,
        second.id,
    ]


@pytest.mark.asyncio
async def test_latest_decision_is_returned(
    db_session,
    user,
):
    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status=LoanApplicationStatus.DRAFT,
        requested_amount=5000,
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    from app.models.policy_version import PolicyVersion
    from app.models.policy_rule import PolicyRule
    from app.models.policy_evaluation import PolicyEvaluation

    policy = PolicyVersion(
        version=f"policy-{uuid4().hex[:8]}",
        effective_from=datetime.now(timezone.utc),
    )
    db_session.add(policy)
    await db_session.flush()

    db_session.add(
        PolicyRule(
            policy_version_id=policy.id,
            code="MANUAL_REVIEW",
            rule_order=1,
            effect="REQUIRE_MANUAL_REVIEW",
            condition={},
        )
    )
    await db_session.flush()

    repository = LoanDecisionRepository(db_session)

    evaluations = []

    for index in range(2):
        evaluation = PolicyEvaluation(
            loan_application_id=application.id,
            user_id=user.id,
            policy_version_id=policy.id,
            policy_version=policy.version,
            decision_route="MANUAL_REVIEW",
            matched_rule_codes=["MANUAL_REVIEW"],
            reasons=[f"Review {index}"],
            input_snapshot={"iteration": index},
            evaluated_at=datetime.now(timezone.utc),
        )
        db_session.add(evaluation)
        await db_session.flush()
        evaluations.append(evaluation)

    await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_evaluation_id=evaluations[0].id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        reason_codes=["MANUAL_REVIEW_REQUIRED"],
        reasons=["First review."],
        input_snapshot={"iteration": 0},
        decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    latest = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
        policy_evaluation_id=evaluations[1].id,
        policy_version=policy.version,
        decision_route="MANUAL_REVIEW",
        reason_codes=["MANUAL_REVIEW_REQUIRED"],
        reasons=["Latest review."],
        input_snapshot={"iteration": 1},
        decided_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    result = await repository.get_latest_for_loan_application(
        application.id
    )

    assert result is not None
    assert result.id == latest.id