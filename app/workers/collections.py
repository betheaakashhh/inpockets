"""Collections worker.

Each pass, in order (each step bounded and safe to repeat):
  1. DPD sync: open, refresh or close cases from the repayment schedules;
  2. reminders: create the reminder requests now due (only when switched on);
  3. escalation: raise cases whose days past due crossed a threshold.

Safe on several instances at once: every step locks the schedule or case row
first, and reminders/escalations carry a per-case dedupe key the database
enforces, so a repeat creates nothing. Nothing here contacts a customer.

Run:  python -m app.workers.collections           (loop)
      python -m app.workers.collections --once    (single pass)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import sys

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.services.collections_factory import build_collection_service

logger = logging.getLogger(__name__)


async def run_once(*, session_factory=AsyncSessionLocal, today=None) -> dict[str, int]:
    stats = {"opened": 0, "updated": 0, "closed": 0, "reminders": 0, "escalated": 0, "errors": 0}

    async with session_factory() as session:
        schedule_ids = await build_collection_service(session).sync_candidates(today=today)
    for schedule_id in schedule_ids:
        try:
            async with session_factory() as session:
                result = await build_collection_service(session).sync_schedule(schedule_id, today=today)
                await session.commit()
            if result.action in ("opened", "updated", "closed"):
                stats[result.action] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("collections sync failed schedule=%s", schedule_id)

    async with session_factory() as session:
        case_ids = await build_collection_service(session).reminder_candidates()
    for case_id in case_ids:
        try:
            async with session_factory() as session:
                stats["reminders"] += await build_collection_service(session).schedule_reminders(case_id)
                await session.commit()
        except Exception:
            stats["errors"] += 1
            logger.exception("collections reminders failed case=%s", case_id)

    async with session_factory() as session:
        case_ids = await build_collection_service(session).escalation_candidates()
    for case_id in case_ids:
        try:
            async with session_factory() as session:
                level = await build_collection_service(session).escalate_case(case_id)
                await session.commit()
            if level is not None:
                stats["escalated"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("collections escalation failed case=%s", case_id)

    logger.info("collections worker pass: %s", stats)
    return stats


async def run_forever(*, interval_seconds: float = 900.0) -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("collections worker pass crashed")
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
    parser.add_argument("--interval", type=float, default=900.0)
    args = parser.parse_args()
    configure_logging()
    if args.once:
        _run(run_once())
    else:
        _run(run_forever(interval_seconds=args.interval))
