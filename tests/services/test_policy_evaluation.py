from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.loan_application import LoanApplicationStatus
from app.domain.policy import PolicyRuleEffect
from app.models.loan_application import LoanApplication
from app.repositories.policy_evaluation import PolicyEvaluationRepository
from app.repositories.policy_rule import PolicyRuleRepository
from app.repositories.policy_version import PolicyVersionRepository
from app.services.policy_engine import PolicyEngine
from app.services.policy_evaluation import PolicyEvaluationService
from app.services.policy_version_selector import PolicyVersionSelector

@pytest.mark.asyncio
async def test_selects_effective_policy_and_persists_evaluation(
    db_session,
    user,
):
    version_repository = PolicyVersionRepository(db_session)
    rule_repository = PolicyRuleRepository(db_session)
    evaluation_repository = PolicyEvaluationRepository(db_session)


    policy = await version_repository.create(
     version="policy-v1",
     effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    await rule_repository.create(
        policy_version_id=policy.id,
        code="MANUAL_REVIEW",
        rule_order=10,
        effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW.value,
        condition={},
        reason_code="MANUAL_REVIEW_REQUIRED",
    )

    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status=LoanApplicationStatus.DRAFT,
        requested_amount=5000,
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    service = PolicyEvaluationService(
        policy_version_selector=PolicyVersionSelector(version_repository),
        policy_rule_repository=rule_repository,
        policy_evaluation_repository=evaluation_repository,
        policy_engine=PolicyEngine(),
    )

    result = await service.evaluate(
        user_id=user.id,
        loan_application_id=application.id,
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        input_snapshot={
            "risk_band": "MEDIUM",
            "recommended_amount": "5000",
            "max_eligible_amount": "9000",
    },
)

    assert result.loan_application_id == application.id
    assert result.user_id == user.id
    assert result.policy_version == "policy-v1"
    assert result.policy_version_id == policy.id
    assert result.decision_route == "MANUAL_REVIEW"
    assert result.matched_rule_codes == ["MANUAL_REVIEW"]
    assert result.reasons == ["MANUAL_REVIEW_REQUIRED"]
    assert result.recommended_amount == 5000
    assert result.max_eligible_amount == 9000


@pytest.mark.asyncio
async def test_exact_policy_version_is_persisted_for_historical_reproducibility(
    db_session,
    user,
):
    version_repository = PolicyVersionRepository(db_session)
    rule_repository = PolicyRuleRepository(db_session)
    evaluation_repository = PolicyEvaluationRepository(db_session)


    old_policy = await version_repository.create(
    version="policy-v1",
    effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    effective_to=datetime(2026, 7, 1, tzinfo=timezone.utc),
)

    await rule_repository.create(
        policy_version_id=old_policy.id,
        code="OLD_MANUAL",
        rule_order=10,
        effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW.value,
        condition={},
        reason_code="OLD_POLICY_RULE",
    )

    new_policy = await version_repository.create(
        version="policy-v2",
        effective_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
)

    await rule_repository.create(
    policy_version_id=new_policy.id,
    code="NEW_MANUAL",
    rule_order=10,
    effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW.value,
    condition={},
    reason_code="NEW_POLICY_RULE",
)

    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status=LoanApplicationStatus.DRAFT,
        requested_amount=7000,
        requested_tenure_days=45,
    )
    db_session.add(application)
    await db_session.flush()

    service = PolicyEvaluationService(
        policy_version_selector=PolicyVersionSelector(version_repository),
        policy_rule_repository=rule_repository,
        policy_evaluation_repository=evaluation_repository,
        policy_engine=PolicyEngine(),
    )

    result = await service.evaluate(
        user_id=user.id,
        loan_application_id=application.id,
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        input_snapshot={
            "risk_band": "LOW",
            "recommended_amount": "7000",
            "max_eligible_amount": "10000",
    },
)

    assert result.policy_version == "policy-v2"
    assert result.policy_version_id == new_policy.id
    assert result.decision_route == "MANUAL_REVIEW"
    assert result.matched_rule_codes == ["NEW_MANUAL"]
    assert result.reasons == ["NEW_POLICY_RULE"]


@pytest.mark.asyncio
async def test_fails_when_no_effective_policy_exists(
    db_session,
    user,
):
    version_repository = PolicyVersionRepository(db_session)
    rule_repository = PolicyRuleRepository(db_session)
    evaluation_repository = PolicyEvaluationRepository(db_session)


    policy = await version_repository.create(
        version="policy-v1",
        effective_from=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )

    await rule_repository.create(
        policy_version_id=policy.id,
        code="MANUAL_REVIEW",
        rule_order=10,
        effect=PolicyRuleEffect.REQUIRE_MANUAL_REVIEW.value,
        condition={},
        reason_code="MANUAL_REVIEW_REQUIRED",
    )

    application = LoanApplication(
        application_number=f"APP-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status=LoanApplicationStatus.DRAFT,
        requested_amount=5000,
        requested_tenure_days=30,
    )
    db_session.add(application)
    await db_session.flush()

    service = PolicyEvaluationService(
        policy_version_selector=PolicyVersionSelector(version_repository),
        policy_rule_repository=rule_repository,
        policy_evaluation_repository=evaluation_repository,
        policy_engine=PolicyEngine(),
    )

    with pytest.raises(ValueError, match="no effective policy version"):
     await service.evaluate(
        user_id=user.id,
        loan_application_id=application.id,
        evaluated_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        input_snapshot={
            "risk_band": "MEDIUM",
            "recommended_amount": "5000",
            "max_eligible_amount": "9000",
        },
    )

