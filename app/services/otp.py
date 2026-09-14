import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
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


class OTPService:
    def __init__(self, repository: OTPVerificationRepository):
        self.repository = repository

    async def create_otp(
        self,
        *,
        phone_number: str,
        purpose: str = "login",
    ) -> tuple[OTPVerification, str]:
        otp = generate_otp()
        otp_hash = hash_otp(otp)

        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=OTP_EXPIRY_MINUTES
        )

        record = await self.repository.create(
            phone_number=phone_number,
            otp_hash=otp_hash,
            expires_at=expires_at,
            purpose=purpose,
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

        if not verify_otp_hash(otp, record.otp_hash):
            record.attempts += 1
            await self.repository.update(record)
            raise OTPInvalidError

        record.verified_at = now

        await self.repository.update(record)

        return record