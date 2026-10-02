from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_level import LoanLevel


class LoanLevelRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        code: str,
        name: str,
        min_amount,
        max_amount,
        min_tenure_days: int,
        max_tenure_days: int,
        description: str | None = None,
    ) -> LoanLevel:
        loan_level = LoanLevel(
            code=code,
            name=name,
            min_amount=min_amount,
            max_amount=max_amount,
            min_tenure_days=min_tenure_days,
            max_tenure_days=max_tenure_days,
            description=description,
        )

        self.session.add(loan_level)
        await self.session.flush()

        return loan_level

    async def get_by_id(
        self,
        loan_level_id: UUID,
    ) -> LoanLevel | None:
        result = await self.session.execute(
            select(LoanLevel).where(
                LoanLevel.id == loan_level_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code(
        self,
        code: str,
    ) -> LoanLevel | None:
        result = await self.session.execute(
            select(LoanLevel).where(
                LoanLevel.code == code
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[LoanLevel]:
        result = await self.session.execute(
            select(LoanLevel).order_by(
                LoanLevel.min_amount.asc(),
                LoanLevel.code.asc(),
            )
        )
        return list(result.scalars().all())