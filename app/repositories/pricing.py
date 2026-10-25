from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import LoanOfferPricing, PricingVersion

_VERSION_LOCK_KEY = 7_204_001  # serialises version-number allocation


class PricingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(self, **fields) -> PricingVersion:
        """Allocate the next number under an advisory lock (released at
        commit/rollback) so two admins cannot take the same number."""
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _VERSION_LOCK_KEY})
        current = (await self.session.execute(select(func.max(PricingVersion.version)))).scalar()
        row = PricingVersion(version=(current or 0) + 1, **fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, version_id: uuid.UUID, *, for_update: bool = False) -> PricingVersion | None:
        stmt = select(PricingVersion).where(PricingVersion.id == version_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_versions(self, *, limit: int = 100) -> list[PricingVersion]:
        rows = await self.session.execute(
            select(PricingVersion).order_by(PricingVersion.version.desc()).limit(limit)
        )
        return list(rows.scalars())

    async def get_effective(self, on: date) -> PricingVersion | None:
        """The approved version with the latest effective date not after `on`."""
        stmt = (
            select(PricingVersion)
            .where(PricingVersion.status == "APPROVED", PricingVersion.effective_from <= on)
            .order_by(PricingVersion.effective_from.desc(), PricingVersion.version.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_any_approved(self) -> bool:
        stmt = select(PricingVersion.id).where(PricingVersion.status == "APPROVED").limit(1)
        return (await self.session.execute(stmt)).first() is not None

    async def add_snapshot(self, **fields) -> LoanOfferPricing:
        row = LoanOfferPricing(**fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_snapshot(self, loan_offer_id: uuid.UUID) -> LoanOfferPricing | None:
        stmt = select(LoanOfferPricing).where(LoanOfferPricing.loan_offer_id == loan_offer_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
