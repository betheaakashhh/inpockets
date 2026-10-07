from __future__ import annotations
from datetime import datetime, timezone

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.underwriting_override import UnderwritingOverride


class UnderwritingOverrideRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        review_case_id: UUID,
        requested_by_admin_user_id: UUID,
        override_type: str,
        original_value: dict[str, object],
        requested_value: dict[str, object],
        reason: str,
    ) -> UnderwritingOverride:
        override = UnderwritingOverride(
            review_case_id=review_case_id,
            requested_by_admin_user_id=requested_by_admin_user_id,
            override_type=override_type,
            original_value=original_value,
            requested_value=requested_value,
            reason=reason,
        )

        self.session.add(override)
        await self.session.flush()
        await self.session.refresh(override)

        return override

    async def get_by_id(
        self,
        *,
        override_id: UUID,
    ) -> UnderwritingOverride | None:
        result = await self.session.execute(
            select(UnderwritingOverride).where(
                UnderwritingOverride.id == override_id
            )
        )

        return result.scalar_one_or_none()

    async def list_by_review_case(
        self,
        *,
        review_case_id: UUID,
    ) -> list[UnderwritingOverride]:
        result = await self.session.execute(
            select(UnderwritingOverride)
            .where(
                UnderwritingOverride.review_case_id == review_case_id
            )
            .order_by(
                UnderwritingOverride.created_at.asc(),
                UnderwritingOverride.id.asc(),
            )
        )

        return list(result.scalars().all())

    async def list_by_status(
        self,
        *,
        status: str,
    ) -> list[UnderwritingOverride]:
        result = await self.session.execute(
            select(UnderwritingOverride)
            .where(
                UnderwritingOverride.status == status
            )
            .order_by(
                UnderwritingOverride.created_at.asc(),
                UnderwritingOverride.id.asc(),
            )
        )

        return list(result.scalars().all())
        
    async def approve(
        self,
        *,
        override_id: UUID,
        approved_by_admin_user_id: UUID,
) -> UnderwritingOverride:
        override = await self.get_by_id(override_id=override_id)

        if override is None:
            raise ValueError("underwriting override not found")

        override.status = "APPROVED"
        override.approved_by_admin_user_id = approved_by_admin_user_id
        override.approved_at = datetime.now(timezone.utc)

        await self.session.flush()
        await self.session.refresh(override)

        return override


    async def reject(
        self,
        *,
        override_id: UUID,
) -> UnderwritingOverride:
        override = await self.get_by_id(override_id=override_id)

        if override is None:
            raise ValueError("underwriting override not found")

        override.status = "REJECTED"
        override.rejected_at = datetime.now(timezone.utc)

        await self.session.flush()
        await self.session.refresh(override)

        return override