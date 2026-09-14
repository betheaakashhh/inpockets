from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp_verification import OTPVerification


class OTPVerificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        phone_number: str,
        otp_hash: str,
        expires_at: datetime,
        purpose: str = "login",
        user_id=None,
    ) -> OTPVerification:
        otp = OTPVerification(
            user_id=user_id,
            phone_number=phone_number,
            otp_hash=otp_hash,
            purpose=purpose,
            expires_at=expires_at,
        )

        self.session.add(otp)
        await self.session.flush()

        return otp

    async def get_latest(
        self,
        *,
        phone_number: str,
        purpose: str = "login",
    ) -> OTPVerification | None:
        result = await self.session.execute(
            select(OTPVerification)
            .where(
                OTPVerification.phone_number == phone_number,
                OTPVerification.purpose == purpose,
            )
            .order_by(OTPVerification.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def update(self, otp: OTPVerification) -> OTPVerification:
        await self.session.flush()
        return otp