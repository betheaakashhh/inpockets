from __future__ import annotations

from datetime import datetime

from app.models.policy_version import PolicyVersion
from app.repositories.policy_version import PolicyVersionRepository


class PolicyVersionSelector:
    """Select the policy version effective at a specific evaluation time."""

    def __init__(self, repository: PolicyVersionRepository):
        self.repository = repository

    async def select(
        self,
        *,
        evaluated_at: datetime,
    ) -> PolicyVersion:
        policy_version = await self.repository.get_effective_at(evaluated_at)

        if policy_version is None:
            raise ValueError(
                "no effective policy version exists for the evaluation time"
            )

        return policy_version