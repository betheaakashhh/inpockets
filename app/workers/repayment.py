"""Repayment worker.

Safe to run on several instances at once. Each pass:
  1. dispatch: INITIATED payments the provider may never have received
     (a crash or timeout after we recorded them) are sent again. The provider
     dedupes on the payment's idempotency key, so this cannot double-collect;
  2. reconcile: PENDING payments with no answer after a grace period are
     looked up at the provider. The provider's answer, not ours, decides;
  3. late charges: overdue installments of loans whose offer switched late
     charges on are charged for any day not yet charged (idempotent).

Run:  python -m app.workers.repayment           (loop)
      python -m app.workers.repayment --once    (single pass)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import sys

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.services.late_charges_factory import build_late_charge_service
from app.services.repayment_factory import build_repayment_service

logger = logging.getLogger(__name__)


async def run_once(*, session_factory=AsyncSessionLocal, batch_size: int = 50) -> dict[str, int]:
    stats = {"dispatched": 0, "reconciled": 0, "late_charged": 0, "errors": 0}

    async with session_factory() as session:
        undispatched = await build_repayment_service(session).undispatched_candidates(
            limit=batch_size
        )
    for payment_id in undispatched:
        try:
            async with session_factory() as session:
                await build_repayment_service(session).dispatch_payment(payment_id)
                await session.commit()
            stats["dispatched"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("repayment dispatch failed id=%s", payment_id)

    async with session_factory() as session:
        candidates = await build_repayment_service(session).reconcile_candidates(limit=batch_size)
    for payment_id in candidates:
        try:
            async with session_factory() as session:
                await build_repayment_service(session).reconcile_one(payment_id)
                await session.commit()
            stats["reconciled"] += 1
        except Exception:
            stats["errors"] += 1
            logger.exception("repayment reconcile failed id=%s", payment_id)

    async with session_factory() as session:
        overdue = await build_late_charge_service(session).candidates(limit=batch_size * 4)
    for schedule_id in overdue:
        try:
            async with session_factory() as session:
                result = await build_late_charge_service(session).assess_schedule(schedule_id)
                await session.commit()
            stats["late_charged"] += result.charges
        except Exception:
            stats["errors"] += 1
            logger.exception("late charge assessment failed id=%s", schedule_id)

    logger.info("repayment worker pass: %s", stats)
    return stats


async def run_forever(*, interval_seconds: float = 15.0) -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("repayment worker pass crashed")
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
