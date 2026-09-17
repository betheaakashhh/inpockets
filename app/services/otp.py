import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis

from app.core.config import settings
from app.core.sms import sms_service
from app.models.otp_verification import OTPVerification
from app.repositories.otp_verification import OTPVerificationRepository


OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 5


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        otp.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_otp_hash(otp: str, otp_hash: str) -> bool:
    expected_hash = hash_otp(otp)
    return hmac.compare_digest(expected_hash, otp_hash)


class OTPError(Exception):
    """Base exception for OTP-related errors."""


class OTPExpiredError(OTPError):
    pass


class OTPAlreadyVerifiedError(OTPError):
    pass


class OTPAttemptsExceededError(OTPError):
    pass


class OTPInvalidError(OTPError):
    pass


class OTPCooldownError(OTPError):
    pass


class OTPRateLimitError(OTPError):
    pass


class OTPService:

    def __init__(self, repository: OTPVerificationRepository):
        self.repository = repository

    async def check_request_rate_limit(
        self,
        *,
        phone_number: str,
    ) -> None:
        key = f"otp:request:{phone_number}"

        redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

        try:
            count = await redis_client.incr(key)

            if count == 1:
                await redis_client.expire(
                    key,
                    settings.otp_request_window_seconds,
                )
        finally:
            await redis_client.aclose()

        if count > settings.otp_request_limit:
            raise OTPRateLimitError(
                "Too many OTP requests. Please try again later."
            )

    async def create_otp(
        self,
        *,
        phone_number: str,
        purpose: str = "login",
    ) -> tuple[OTPVerification, str]:

        await self.check_request_rate_limit(
            phone_number=phone_number,
        )

        latest_otp = await self.repository.get_latest(
            phone_number=phone_number,
            purpose=purpose,
        )

        now = datetime.now(timezone.utc)

        if latest_otp is not None:
            cooldown_until = (
                latest_otp.created_at
                + timedelta(
                    seconds=settings.otp_resend_cooldown_seconds,
                )
            )

            if now < cooldown_until:
                remaining_seconds = int(
                    (cooldown_until - now).total_seconds()
                )

                raise OTPCooldownError(
                    f"OTP resend available in {remaining_seconds + 1} seconds"
                )

        otp = generate_otp()

        otp_hash = hash_otp(otp)

        expires_at = now + timedelta(
            minutes=OTP_EXPIRY_MINUTES,
        )

        record = await self.repository.create(
            phone_number=phone_number,
            otp_hash=otp_hash,
            expires_at=expires_at,
            purpose=purpose,
        )

        # Send OTP only after it has been successfully persisted.
        await sms_service.send_otp(
            phone_number=phone_number,
            otp=otp,
        )

        return record, otp

    async def verify_otp(
        self,
        *,
        record: OTPVerification,
        otp: str,
    ) -> OTPVerification:

        now = datetime.now(timezone.utc)

        if record.verified_at is not None:
            raise OTPAlreadyVerifiedError

        if now >= record.expires_at:
            raise OTPExpiredError

        if record.attempts >= MAX_OTP_ATTEMPTS:
            raise OTPAttemptsExceededError

        if not verify_otp_hash(
            otp,
            record.otp_hash,
        ):
            record.attempts += 1

            await self.repository.update(
                record,
            )

            raise OTPInvalidError

        record.verified_at = now

        await self.repository.update(
            record,
        )

        return record