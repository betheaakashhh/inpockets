import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.sms import sms_service
from app.models.otp_verification import OTPVerification
from app.repositories.otp_verification import OTPVerificationRepository

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 5


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    return hmac.new(
        settings.otp_hash_secret.encode(),
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


class OTPServiceUnavailableError(OTPError):
    pass


class OTPSMSDeliveryError(OTPError):
    pass


_RATE_LIMIT_CHECK_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if count > tonumber(ARGV[2]) then
    return 0
end
return 1
"""

_RATE_LIMIT_RESERVE_SCRIPT = """
local count = redis.call('HGET', KEYS[1], '__count')
if not count then
    count = 0
end

if tonumber(count) >= tonumber(ARGV[2]) then
    return 0
end

redis.call('HINCRBY', KEYS[1], '__count', 1)
redis.call('HSET', KEYS[1], ARGV[1], '1')
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

_RATE_LIMIT_COMMIT_SCRIPT = """
if redis.call('HGET', KEYS[1], ARGV[1]) then
    redis.call('HDEL', KEYS[1], ARGV[1])
    return 1
end
return 0
"""

_RATE_LIMIT_RELEASE_SCRIPT = """
if redis.call('HGET', KEYS[1], ARGV[1]) then
    redis.call('HDEL', KEYS[1], ARGV[1])
    local count = redis.call('HINCRBY', KEYS[1], '__count', -1)
    if count <= 0 then
        redis.call('DEL', KEYS[1])
    end
    return 1
end
return 0
"""


class OTPService:
    def __init__(self, repository: OTPVerificationRepository):
        self.repository = repository

    async def _check_rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

        try:
            allowed = await redis_client.eval(
                _RATE_LIMIT_CHECK_SCRIPT,
                1,
                key,
                window_seconds,
                limit,
            )
        except RedisError as exc:
            raise OTPServiceUnavailableError(
                "OTP rate limiting service is temporarily unavailable."
            ) from exc
        finally:
            await redis_client.aclose()

        if int(allowed) != 1:
            raise OTPRateLimitError(
                "Too many OTP requests. Please try again later."
            )

    async def _reserve_rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[str, Redis]:
        redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        reservation_token = secrets.token_hex(16)

        try:
            allowed = await redis_client.eval(
                _RATE_LIMIT_RESERVE_SCRIPT,
                1,
                key,
                reservation_token,
                limit,
                window_seconds,
            )
        except RedisError as exc:
            await redis_client.aclose()
            raise OTPServiceUnavailableError(
                "OTP rate limiting service is temporarily unavailable."
            ) from exc

        if int(allowed) != 1:
            await redis_client.aclose()
            raise OTPRateLimitError(
                "Too many OTP requests. Please try again later."
            )

        return reservation_token, redis_client

    async def _commit_rate_limit(
        self,
        *,
        key: str,
        reservation_token: str,
        redis_client: Redis,
    ) -> None:
        try:
            await redis_client.eval(
                _RATE_LIMIT_COMMIT_SCRIPT,
                1,
                key,
                reservation_token,
            )
        except RedisError:
            logger.exception(
                "Failed to finalize OTP rate-limit reservation for key=%s",
                key,
            )
        finally:
            await redis_client.aclose()

    async def _release_rate_limit(
        self,
        *,
        key: str,
        reservation_token: str,
        redis_client: Redis,
    ) -> None:
        try:
            await redis_client.eval(
                _RATE_LIMIT_RELEASE_SCRIPT,
                1,
                key,
                reservation_token,
            )
        except RedisError:
            logger.exception(
                "Failed to release OTP rate-limit reservation for key=%s",
                key,
            )
        finally:
            await redis_client.aclose()

    async def check_request_rate_limit(
        self,
        *,
        phone_number: str,
    ) -> None:
        await self._check_rate_limit(
            key=f"otp:request:{phone_number}",
            limit=settings.otp_request_limit,
            window_seconds=settings.otp_request_window_seconds,
        )

    async def check_verify_rate_limit(
        self,
        *,
        phone_number: str,
        client_ip: str | None,
    ) -> None:
        await self._check_rate_limit(
            key=f"otp:verify:phone:{phone_number}",
            limit=settings.otp_verify_limit,
            window_seconds=settings.otp_verify_window_seconds,
        )

        if client_ip is not None:
            await self._check_rate_limit(
                key=f"otp:verify:ip:{client_ip}",
                limit=settings.otp_verify_limit * 3,
                window_seconds=settings.otp_verify_window_seconds,
            )

    async def create_otp(
        self,
        *,
        phone_number: str,
        purpose: str = "login",
    ) -> tuple[OTPVerification, str]:
        rate_limit_key = f"otp:request:{phone_number}"

        reservation_token, redis_client = await self._reserve_rate_limit(
            key=rate_limit_key,
            limit=settings.otp_request_limit,
            window_seconds=settings.otp_request_window_seconds,
        )
        reservation_active = True

        try:
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
            expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)

            record = await self.repository.create(
                phone_number=phone_number,
                otp_hash=otp_hash,
                expires_at=expires_at,
                purpose=purpose,
            )

            try:
                await sms_service.send_otp(
                    phone_number=phone_number,
                    otp=otp,
                )
            except Exception as exc:
                logger.exception(
                    "OTP SMS delivery failed for phone=%s",
                    phone_number,
                )
                await self._release_rate_limit(
                    key=rate_limit_key,
                    reservation_token=reservation_token,
                    redis_client=redis_client,
                )
                reservation_active = False
                raise OTPSMSDeliveryError(
                    "OTP could not be sent. Please try again later."
                ) from exc

            await self._commit_rate_limit(
                key=rate_limit_key,
                reservation_token=reservation_token,
                redis_client=redis_client,
            )
            reservation_active = False

            return record, otp
        except Exception:
            if reservation_active:
                await self._release_rate_limit(
                    key=rate_limit_key,
                    reservation_token=reservation_token,
                    redis_client=redis_client,
                )
                reservation_active = False
            raise

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

            await self.repository.update(record)

            raise OTPInvalidError

        record.verified_at = now

        await self.repository.update(record)

        return record
