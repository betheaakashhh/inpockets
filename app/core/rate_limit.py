"""Redis fixed-window rate limiting as FastAPI dependencies.

Keys are per authenticated user (or per client IP for unauthenticated
webhooks). If Redis is unreachable the limiter fails open and logs, so a
cache outage cannot take payments down; business-level limits (for example
bank verification attempts per day) are enforced in PostgreSQL regardless.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.auth import get_current_user
from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.models.user import User

logger = logging.getLogger(__name__)

_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""

WINDOW_SECONDS = 60


async def enforce(*, scope: str, identifier: str, limit: int) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        count, ttl = await client.eval(
            _SCRIPT, 1, f"ratelimit:{scope}:{identifier}", WINDOW_SECONDS
        )
    except RedisError:
        logger.warning("rate limiter unavailable; failing open (scope=%s)", scope)
        return
    finally:
        try:
            await client.aclose()
        except RedisError:  # pragma: no cover
            pass
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests; slow down",
            headers={"Retry-After": str(max(int(ttl), 1))},
        )


def limit_user(scope: str, *, sensitive: bool = False) -> Callable[..., Awaitable[None]]:
    """Per-user limit. `sensitive` uses the stricter budget."""

    async def dependency(user: User = Depends(get_current_user)) -> None:
        s = get_settings()
        limit = s.rate_limit_sensitive_per_minute if sensitive else s.rate_limit_user_per_minute
        await enforce(scope=scope, identifier=str(user.id), limit=limit)

    return dependency


def limit_ip(scope: str) -> Callable[..., Awaitable[None]]:
    """Per-client-IP limit for unauthenticated endpoints (webhooks)."""

    async def dependency(request: Request) -> None:
        ip = get_client_ip(request) or "unknown"
        await enforce(
            scope=scope,
            identifier=ip,
            limit=get_settings().rate_limit_webhook_per_minute,
        )

    return dependency
