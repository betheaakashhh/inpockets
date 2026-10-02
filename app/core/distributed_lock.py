from __future__ import annotations

import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.exceptions import AppException


class OperationAlreadyInProgressError(AppException):
    """Raised when another worker owns the same provider-operation lock.

    Subclasses AppException so the global handler returns a retryable 409
    instead of an unhandled 500.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            code="OPERATION_IN_PROGRESS",
            message="A similar request is already being processed. Please retry shortly.",
            status_code=409,
        )


@dataclass
class DistributedOperationLock:
    key: str
    ttl_seconds: int = 120

    def __post_init__(self) -> None:
        self._token: str | None = None
        self._redis: Redis | None = None

    async def __aenter__(self) -> DistributedOperationLock:
        self._token = secrets.token_urlsafe(32)
        self._redis = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
        )

        try:
            acquired = await self._redis.set(
                self.key,
                self._token,
                nx=True,
                ex=self.ttl_seconds,
            )
        except Exception:
            await self._redis.aclose()
            self._redis = None
            raise

        if not acquired:
            await self._redis.aclose()
            self._redis = None
            self._token = None
            raise OperationAlreadyInProgressError(self.key)

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._redis is None or self._token is None:
            return

        release_script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """

        try:
            await self._redis.eval(
                release_script,
                1,
                self.key,
                self._token,
            )
        finally:
            await self._redis.aclose()
            self._redis = None
            self._token = None
