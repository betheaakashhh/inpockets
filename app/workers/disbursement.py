"""Disbursement worker.

Safe to run on several instances at once:
  1. claim: PENDING -> PROCESSING, committed *before* any provider call, using
     SKIP LOCKED so two workers never claim the same row;
  2. submit: each claimed row is re-locked (SKIP LOCKED) and sent with its
     idempotency key, so even a duplicate submit cannot pay twice;
  3. reconcile: PROCESSING rows with no answer after a grace period are
     polled; the provider's answer, not ours, decides the outcome.

Run:  python -m app.workers.disbursement           (loop)
      python -m app.workers.disbursement --once    (single pass)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import sys

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.services.disbursement_factory import build_disbursement_service

logger = logging.getLogger(__name__)


async def run_once(*, session_factory=AsyncSessionLocal, batch_size: int = 20) -> dict[str, int]:
    stats: dict[str, int] = {"claimed": 0, "submitted": 0, "reconciled": 0, "errors": 0}

    async with session_factory() as session:
        claimed = await build_disbursement_service(session).claim_pending(batch_size=batch_size)
        await session.commit()
    stats["claimed"] = len(claimed)

    for disbursement_id in claimed:
        try:
            async with session_factory() as session:
                await build_disbursement_service(session).submit_claimed(disbursement_id)
                await session.commit()
            stats["submitted"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("disbursement submit failed id=%s", disbursement_id)

    async with session_factory() as session:
        candidates = await build_disbursement_service(session).reconcile_candidates(
            limit=batch_size
        )
    for disbursement_id in candidates:
        try:
            async with session_factory() as session:
                await build_disbursement_service(session).reconcile_one(disbursement_id)
                await session.commit()
            stats["reconciled"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("disbursement reconcile failed id=%s", disbursement_id)

    logger.info("disbursement worker pass: %s", stats)
    return stats


async def run_forever(*, interval_seconds: float = 15.0) -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("disbursement worker pass crashed")
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
