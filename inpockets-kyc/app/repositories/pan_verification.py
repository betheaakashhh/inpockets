import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pan_verification import PANVerification


class PANVerificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        pan_number_masked: str,
        provider: str,
        provider_ref: str,
        status: str,
        verified_name: str | None = None,
        name_match_result: str | None = None,
        failure_reason: str | None = None,
    ) -> PANVerification:
        record = PANVerification(
            user_id=user_id,
            pan_number_masked=pan_number_masked,
            provider=provider,
            provider_ref=provider_ref,
            status=status,
            verified_name=verified_name,
            name_match_result=name_match_result,
            failure_reason=failure_reason,
        )

        self.session.add(record)
        await self.session.flush()

        return record

    async def get_latest_for_user(
        self,
        *,
        user_id: uuid.UUID,
    ) -> PANVerification | None:
        result = await self.session.execute(
            select(PANVerification)
            .where(PANVerification.user_id == user_id)
            .order_by(PANVerification.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()
