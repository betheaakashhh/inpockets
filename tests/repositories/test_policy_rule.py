from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.repositories.policy_rule import PolicyRuleRepository
from app.repositories.policy_version import PolicyVersionRepository


async def create_policy_version(db_session, version="policy-v1"):
    repository = PolicyVersionRepository(db_session)

    return await repository.create(
        version=version,
        effective_from=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_policy_rule(db_session):
    policy_version = await create_policy_version(db_session)

    repository = PolicyRuleRepository(db_session)

    rule = await repository.create(
        policy_version_id=policy_version.id,
        code="REQUIRE_MANUAL_REVIEW",
        rule_order=10,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={
            "always": True,
        },
        reason_code="MANUAL_REVIEW_REQUIRED",
        description="All applications require lender admin review.",
    )

    assert rule.id is not None
    assert rule.policy_version_id == policy_version.id
    assert rule.code == "REQUIRE_MANUAL_REVIEW"
    assert rule.rule_order == 10
    assert rule.effect == "REQUIRE_MANUAL_REVIEW"
    assert rule.condition["always"] is True

    await db_session.commit()


@pytest.mark.asyncio
async def test_get_by_id(db_session):
    policy_version = await create_policy_version(db_session)

    repository = PolicyRuleRepository(db_session)

    rule = await repository.create(
        policy_version_id=policy_version.id,
        code="MANUAL_REVIEW",
        rule_order=1,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={"always": True},
    )

    result = await repository.get_by_id(rule.id)

    assert result is not None
    assert result.id == rule.id
    assert result.code == "MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_list_by_policy_version_preserves_rule_order(db_session):
    policy_version = await create_policy_version(db_session)

    repository = PolicyRuleRepository(db_session)

    await repository.create(
        policy_version_id=policy_version.id,
        code="RULE_20",
        rule_order=20,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={},
    )

    await repository.create(
        policy_version_id=policy_version.id,
        code="RULE_10",
        rule_order=10,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={},
    )

    await repository.create(
        policy_version_id=policy_version.id,
        code="RULE_30",
        rule_order=30,
        effect="REQUIRE_ADDITIONAL_INFORMATION",
        condition={},
    )

    results = await repository.list_by_policy_version(
        policy_version.id
    )

    assert [rule.rule_order for rule in results] == [10, 20, 30]
    assert [rule.code for rule in results] == [
        "RULE_10",
        "RULE_20",
        "RULE_30",
    ]


@pytest.mark.asyncio
async def test_get_by_code(db_session):
    policy_version = await create_policy_version(db_session)

    repository = PolicyRuleRepository(db_session)

    created = await repository.create(
        policy_version_id=policy_version.id,
        code="CREDIT_CHECK",
        rule_order=10,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={
            "credit_score_required": True,
        },
    )

    result = await repository.get_by_code(
        policy_version_id=policy_version.id,
        code="CREDIT_CHECK",
    )

    assert result is not None
    assert result.id == created.id
    assert result.code == "CREDIT_CHECK"


@pytest.mark.asyncio
async def test_duplicate_rule_code_is_rejected(db_session):
    policy_version = await create_policy_version(db_session)

    repository = PolicyRuleRepository(db_session)

    await repository.create(
        policy_version_id=policy_version.id,
        code="DUPLICATE_CODE",
        rule_order=10,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={},
    )

    await db_session.commit()

    with pytest.raises(IntegrityError):
        await repository.create(
            policy_version_id=policy_version.id,
            code="DUPLICATE_CODE",
            rule_order=20,
            effect="REQUIRE_MANUAL_REVIEW",
            condition={},
        )

    await db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_rule_order_is_rejected(db_session):
    policy_version = await create_policy_version(db_session)

    repository = PolicyRuleRepository(db_session)

    await repository.create(
        policy_version_id=policy_version.id,
        code="RULE_A",
        rule_order=10,
        effect="REQUIRE_MANUAL_REVIEW",
        condition={},
    )

    await db_session.commit()

    with pytest.raises(IntegrityError):
        await repository.create(
            policy_version_id=policy_version.id,
            code="RULE_B",
            rule_order=10,
            effect="REQUIRE_ADDITIONAL_INFORMATION",
            condition={},
        )

    await db_session.rollback()