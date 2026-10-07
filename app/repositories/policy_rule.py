from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy_rule import PolicyRule


class PolicyRuleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        policy_version_id: UUID,
        code: str,
        rule_order: int,
        effect: str,
        condition: dict,
        reason_code: str | None = None,
        description: str | None = None,
    ) -> PolicyRule:
        rule = PolicyRule(
            policy_version_id=policy_version_id,
            code=code,
            rule_order=rule_order,
            effect=effect,
            condition=condition,
            reason_code=reason_code,
            description=description,
        )

        self.session.add(rule)
        await self.session.flush()
        await self.session.refresh(rule)

        return rule

    async def get_by_id(
        self,
        rule_id: UUID,
    ) -> PolicyRule | None:
        result = await self.session.execute(
            select(PolicyRule).where(
                PolicyRule.id == rule_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_policy_version(
        self,
        policy_version_id: UUID,
    ) -> list[PolicyRule]:
        result = await self.session.execute(
            select(PolicyRule)
            .where(
                PolicyRule.policy_version_id == policy_version_id
            )
            .order_by(
                PolicyRule.rule_order.asc(),
                PolicyRule.code.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_by_code(
        self,
        *,
        policy_version_id: UUID,
        code: str,
    ) -> PolicyRule | None:
        result = await self.session.execute(
            select(PolicyRule).where(
                PolicyRule.policy_version_id == policy_version_id,
                PolicyRule.code == code,
            )
        )
        return result.scalar_one_or_none()