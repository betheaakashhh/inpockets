from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.underwriting_review_evidence import UnderwritingReviewEvidence


class UnderwritingReviewEvidenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        review_case_id: UUID,
        added_by_admin_user_id: UUID,
        evidence_type: str,
        reference: str,
        evidence_metadata: dict[str, object],
    ) -> UnderwritingReviewEvidence:
        evidence = UnderwritingReviewEvidence(
            review_case_id=review_case_id,
            added_by_admin_user_id=added_by_admin_user_id,
            evidence_type=evidence_type,
            reference=reference,
            evidence_metadata=evidence_metadata,
        )
        self.session.add(evidence)
        await self.session.flush()
        await self.session.refresh(evidence)
        return evidence

    async def get_by_id(
        self,
        *,
        evidence_id: UUID,
    ) -> UnderwritingReviewEvidence | None:
        result = await self.session.execute(
            select(UnderwritingReviewEvidence).where(
                UnderwritingReviewEvidence.id == evidence_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_review_case(
        self,
        *,
        review_case_id: UUID,
    ) -> list[UnderwritingReviewEvidence]:
        result = await self.session.execute(
            select(UnderwritingReviewEvidence)
            .where(
                UnderwritingReviewEvidence.review_case_id == review_case_id
            )
            .order_by(
                UnderwritingReviewEvidence.created_at.asc(),
                UnderwritingReviewEvidence.id.asc(),
            )
        )
        return list(result.scalars().all())