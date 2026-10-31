"""Notification worker.

Each pass:
  1. intake: turn collection reminder requests (2.15) into notifications;
  2. claim due notifications (committed BEFORE any provider call);
  3. send each one; transient failures retry with backoff, permanent ones and
     exhausted retries are dead-lettered.

Safe on several instances at once (rows are claimed with SKIP LOCKED and a
lease) and safe to repeat (the provider dedupes on the notification's key).

Run:  python -m app.workers.notifications           (loop)
      python -m app.workers.notifications --once    (single pass)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import sys

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.services.notifications_factory import build_notification_service

logger = logging.getLogger(__name__)


async def run_once(*, session_factory=AsyncSessionLocal) -> dict[str, int]:
    stats = {"intake": 0, "claimed": 0, "sent": 0, "retry": 0, "dead": 0, "suppressed": 0, "errors": 0}

    try:
        async with session_factory() as session:
            stats["intake"] = await build_notification_service(session).intake_collection_reminders()
            await session.commit()
    except Exception:
        stats["errors"] += 1
        logger.exception("notification intake failed")

    async with session_factory() as session:
        ids = await build_notification_service(session).claim_due()
        await session.commit()
    stats["claimed"] = len(ids)

    for nid in ids:
        try:
            async with session_factory() as session:
                result = await build_notification_service(session).send_one(nid)
                await session.commit()
            key = {"SENT": "sent", "DELIVERED": "sent", "PENDING": "retry", "DEAD": "dead",
                   "SUPPRESSED": "suppressed"}.get(result)
            if key:
                stats[key] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("notification send failed id=%s", nid)

    logger.info("notification worker pass: %s", stats)
    return stats


async def run_forever(*, interval_seconds: float = 15.0) -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("notification worker pass crashed")
        await asyncio.sleep(interval_seconds)


def _run(coro) -> None:
    """psycopg's async mode cannot use Windows' default ProactorEventLoop."""
    if sys.platform == "win32":
        asyncio.run(
            coro,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(coro)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    configure_logging()
    if args.once:
        _run(run_once())
    else:
        _run(run_forever(interval_seconds=args.interval))
