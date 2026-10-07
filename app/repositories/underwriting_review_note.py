from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.underwriting_review_note import UnderwritingReviewNote


class UnderwritingReviewNoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        review_case_id: UUID,
        author_admin_user_id: UUID,
        content: str,
    ) -> UnderwritingReviewNote:
        note = UnderwritingReviewNote(
            review_case_id=review_case_id,
            author_admin_user_id=author_admin_user_id,
            content=content,
        )
        self.session.add(note)
        await self.session.flush()
        await self.session.refresh(note)
        return note

    async def get_by_id(
        self,
        *,
        note_id: UUID,
    ) -> UnderwritingReviewNote | None:
        result = await self.session.execute(
            select(UnderwritingReviewNote).where(
                UnderwritingReviewNote.id == note_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_review_case(
        self,
        *,
        review_case_id: UUID,
    ) -> list[UnderwritingReviewNote]:
        result = await self.session.execute(
            select(UnderwritingReviewNote)
            .where(UnderwritingReviewNote.review_case_id == review_case_id)
            .order_by(
                UnderwritingReviewNote.created_at.asc(),
                UnderwritingReviewNote.id.asc(),
            )
        )
        return list(result.scalars().all())