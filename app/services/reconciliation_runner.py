"""Runs one reconciliation with the right transaction boundaries.

  1. claim   (commit)  reserve the flow/day so no other worker repeats it;
  2. execute (commit)  fetch, compare, write findings + completion atomically;
  3. on any failure: mark the run FAILED in a fresh transaction (commit), so
     the next pass can retry it safely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.services.reconciliation import ClaimResult
from app.services.reconciliation_factory import build_reconciliation_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunOutcome:
    claim: ClaimResult
    status: str  # COMPLETED | FAILED | SKIPPED
    discrepancies: int = 0


async def run_reconciliation(
    flow,
    report_date: date,
    *,
    session_factory=AsyncSessionLocal,
    actor_user_id: UUID | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    today: date | None = None,
) -> RunOutcome:
    async with session_factory() as session:
        try:
            claim = await build_reconciliation_service(session).claim(
                flow, report_date, actor_user_id=actor_user_id,
                request_id=request_id, ip_address=ip_address, today=today,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    if claim.reason in ("already_completed", "in_progress", "gave_up"):
        return RunOutcome(claim, "SKIPPED")

    try:
        async with session_factory() as session:
            run = await build_reconciliation_service(session).execute(claim.run_id)
            await session.commit()
        problems = 0 if run is None else run.unmatched_count + run.mismatch_count + run.review_count
        return RunOutcome(claim, "COMPLETED", problems)
    except Exception as exc:
        logger.exception("reconciliation run failed run=%s", claim.run_id)
        async with session_factory() as session:
            await build_reconciliation_service(session).mark_failed(claim.run_id, f"{type(exc).__name__}: {exc}")
            await session.commit()
        return RunOutcome(claim, "FAILED")
