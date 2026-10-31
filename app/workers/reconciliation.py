"""Reconciliation worker.

Each pass reconciles every recent past day (yesterday and back a few days) for
both flows that has no completed run yet. Safe on several instances at once
(the run row is claimed first), safe to repeat (a completed day is skipped, a
failed one is retried up to a limit) and bounded (a fixed number of days, a
fixed number of lines per run).

It only records findings. It never edits a payment, payout or ledger entry.

Run:  python -m app.workers.reconciliation           (loop)
      python -m app.workers.reconciliation --once    (single pass)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import sys

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.domain.reconciliation import Flow
from app.services.reconciliation_factory import build_reconciliation_service
from app.services.reconciliation_runner import run_reconciliation

logger = logging.getLogger(__name__)


async def run_once(*, session_factory=AsyncSessionLocal, today=None) -> dict[str, int]:
    stats = {"completed": 0, "failed": 0, "skipped": 0, "discrepancies": 0, "errors": 0}
    for flow in Flow:
        try:
            async with session_factory() as session:
                days = await build_reconciliation_service(session).days_needing_work(
                    flow, today=today
                )
        except Exception:
            stats["errors"] += 1
            logger.exception("reconciliation planning failed flow=%s", flow.value)
            continue
        for day in days:
            try:
                outcome = await run_reconciliation(
                    flow, day, session_factory=session_factory, today=today
                )
            except Exception:
                stats["errors"] += 1
                logger.exception("reconciliation crashed flow=%s day=%s", flow.value, day)
                continue
            stats[outcome.status.lower()] += 1
            stats["discrepancies"] += outcome.discrepancies
    logger.info("reconciliation worker pass: %s", stats)
    return stats


async def run_forever(*, interval_seconds: float = 900.0) -> None:
    while True:
        try:
            await run_once()
        except Exception:
            logger.exception("reconciliation worker pass crashed")
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
