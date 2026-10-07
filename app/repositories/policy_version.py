from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy_version import PolicyVersion


class PolicyVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        version: str,
        effective_from: datetime,
        effective_to: datetime | None = None,
    ) -> PolicyVersion:
        policy_version = PolicyVersion(
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
        )

        self.session.add(policy_version)
        await self.session.flush()
        await self.session.refresh(policy_version)

        return policy_version

    async def get_by_id(
        self,
        policy_version_id: UUID,
    ) -> PolicyVersion | None:
        result = await self.session.execute(
            select(PolicyVersion).where(
                PolicyVersion.id == policy_version_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_version(
        self,
        version: str,
    ) -> PolicyVersion | None:
        result = await self.session.execute(
            select(PolicyVersion).where(
                PolicyVersion.version == version
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[PolicyVersion]:
        result = await self.session.execute(
            select(PolicyVersion).order_by(
                PolicyVersion.effective_from.asc(),
                PolicyVersion.version.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_effective_at(
        self,
        evaluated_at: datetime,
    ) -> PolicyVersion | None:
        result = await self.session.execute(
            select(PolicyVersion)
            .where(
                PolicyVersion.effective_from <= evaluated_at,
                (
                    (PolicyVersion.effective_to.is_(None))
                    | (PolicyVersion.effective_to > evaluated_at)
                ),
            )
            .order_by(
                PolicyVersion.effective_from.desc(),
                PolicyVersion.version.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()