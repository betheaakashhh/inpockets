from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.domain import reconciliation as dom
from app.domain.admin import AdminPermission
from app.domain.repayment import today_ist, utcnow
from app.providers.settlement import SettlementLine, SettlementReportMalformed
from app.repositories.reconciliation import ReconciliationRepository

logger = logging.getLogger(__name__)

ENTITY_RUN = "reconciliation_run"
ENTITY_RECORD = "reconciliation_record"
LOOKUP_CHUNK = 2000
MIN_NOTE = 10
_INTERNAL_TYPE = {
    dom.Flow.COLLECTION: "repayment_payment",
    dom.Flow.DISBURSEMENT: "disbursement",
}


@dataclass(frozen=True)
class ClaimResult:
    run_id: UUID | None
    reason: str  # claimed | retaken | already_completed | in_progress | gave_up


class ReconciliationService:
    """Compares our payments, payouts and ledger with the provider's settlement
    report. It only ever WRITES findings. It never edits a payment, a payout or
    a ledger entry to make the numbers agree: a person reviews every difference
    and any correction goes through the normal repayment/ledger flows."""

    def __init__(
        self,
        *,
        session,
        repository: ReconciliationRepository,
        admin_user_repository,
        admin_authorization_service,
        audit_log_service,
        provider,
        settings,
    ):
        self.session = session
        self.repository = repository
        self.admin_users = admin_user_repository
        self.authz = admin_authorization_service
        self.audit = audit_log_service
        self.provider = provider
        self.settings = settings

    # ----------------------------------------------------------- helpers

    def internal_provider(self, flow: dom.Flow) -> str:
        """The payment/payout provider whose items this report covers."""
        if flow == dom.Flow.COLLECTION:
            return self.settings.payment_provider.lower()
        return self.settings.disbursement_provider.lower()

    async def _require(self, actor_user_id, permission: AdminPermission):
        await self.authz.require_permission(user_id=actor_user_id, permission=permission)

    def default_days(self, today: date | None = None) -> list[date]:
        """Yesterday and back `reconciliation_lookback_days` days, oldest first."""
        today = today or today_ist()
        n = max(1, int(self.settings.reconciliation_lookback_days))
        return [today - timedelta(days=i) for i in range(n, 0, -1)]

    async def days_needing_work(self, flow: dom.Flow, *, today: date | None = None) -> list[date]:
        return await self.repository.days_needing_work(
            flow=flow.value,
            provider=self.provider.name,
            days=self.default_days(today),
            max_attempts=int(self.settings.reconciliation_max_attempts),
        )

    # ------------------------------------------------------------- claim

    async def claim(
        self,
        flow,
        report_date: date,
        *,
        actor_user_id: UUID | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        today: date | None = None,
    ) -> ClaimResult:
        """Reserve one flow/day. Several workers may call this at once: the
        unique (flow, provider, day) row lets exactly one of them proceed."""
        flow = dom.Flow(flow)
        if actor_user_id is not None:
            await self._require(actor_user_id, AdminPermission.RECONCILIATION_RUN)
        today = today or today_ist()
        if report_date >= today:
            raise dom.ReconciliationError(
                "Only a past day can be reconciled; today's settlement is not final yet"
            )
        if report_date < today - timedelta(days=366):
            raise dom.ReconciliationError("That day is too far in the past to reconcile")

        admin_id = None
        if actor_user_id is not None:
            admin = await self.admin_users.get_by_user_id(actor_user_id)
            admin_id = admin.id if admin else None

        provider = self.provider.name
        created = await self.repository.insert_run(
            flow=flow.value,
            provider=provider,
            report_date=report_date,
            status=dom.RunStatus.RUNNING.value,
            attempts=1,
            triggered_by_admin_user_id=admin_id,
        )
        run = await self.repository.get_run_for_day(flow.value, provider, report_date, for_update=True)
        reason = "claimed"
        if not created:
            now = utcnow()
            stale_after = timedelta(minutes=int(self.settings.reconciliation_stale_minutes))
            if run.status == dom.RunStatus.COMPLETED.value:
                return ClaimResult(run.id, "already_completed")
            if run.status == dom.RunStatus.RUNNING.value:
                if run.updated_at > now - stale_after:
                    return ClaimResult(run.id, "in_progress")
                reason = "retaken"
            elif actor_user_id is None and run.attempts >= int(self.settings.reconciliation_max_attempts):
                return ClaimResult(run.id, "gave_up")
            else:
                reason = "retaken"
            run.status = dom.RunStatus.RUNNING.value
            run.attempts += 1
            run.error = None
            run.started_at = now
            if admin_id is not None:
                run.triggered_by_admin_user_id = admin_id
            await self.session.flush()

        if actor_user_id is not None:
            await self.audit.record_admin_action(
                actor_user_id=actor_user_id,
                action="RECONCILIATION_RUN_STARTED",
                entity_type=ENTITY_RUN,
                entity_id=str(run.id),
                request_id=request_id,
                ip_address=ip_address,
                new_value={"flow": flow.value, "report_date": report_date.isoformat()},
            )
        return ClaimResult(run.id, reason)

    async def mark_failed(self, run_id: UUID, message: str) -> None:
        run = await self.repository.get_run(run_id, for_update=True)
        if run is None or run.status != dom.RunStatus.RUNNING.value:
            return
        run.status = dom.RunStatus.FAILED.value
        run.error = message[:200]
        await self.session.flush()
        await self.audit.record_system_action(
            action="RECONCILIATION_RUN_FAILED",
            entity_type=ENTITY_RUN,
            entity_id=str(run.id),
            new_value={"flow": run.flow, "report_date": run.report_date.isoformat(),
                       "attempts": run.attempts, "error": run.error},
        )

    # ----------------------------------------------------------- execute

    @staticmethod
    def _clean(lines: list[SettlementLine]) -> list[dom.ExternalLine]:
        out = []
        for ln in lines:
            try:
                amount = Decimal(ln.amount)
            except (InvalidOperation, TypeError) as exc:
                raise SettlementReportMalformed("a settlement line has no valid amount") from exc
            status = str(ln.status).upper()
            if (
                not ln.provider_ref
                or not ln.line_id
                or not amount.is_finite()
                or amount < 0
                or status not in {s.value for s in dom.ProviderStatus}
            ):
                raise SettlementReportMalformed("a settlement line is unusable")
            out.append(dom.ExternalLine(str(ln.line_id), str(ln.provider_ref), amount, status))
        return out

    async def execute(self, run_id: UUID):
        """Fetch the report, compare, and write every finding in ONE
        transaction together with the run's completion: a crash leaves nothing
        half-written. Raises on provider trouble (the caller marks the run
        FAILED in a fresh transaction)."""
        run = await self.repository.get_run(run_id, for_update=True)
        if run is None or run.status != dom.RunStatus.RUNNING.value:
            return run  # finished or taken by someone else meanwhile
        flow = dom.Flow(run.flow)
        limit = int(self.settings.reconciliation_max_lines)

        lines = await self.provider.fetch_report(flow=flow.value, report_date=run.report_date)
        if len(lines) > limit:
            raise dom.ReconciliationError("The settlement report is larger than the safe limit")
        external = self._clean(lines)

        start, end = dom.day_window(run.report_date)
        provider = self.internal_provider(flow)
        window_rows = await self.repository.items_in_window(
            flow, provider=provider, start=start, end=end, limit=limit + 1
        )
        if len(window_rows) > limit:
            raise dom.ReconciliationError("Too many of our own items for one safe run")

        refs = list({e.ref for e in external})
        looked: list = []
        for i in range(0, len(refs), LOOKUP_CHUNK):
            looked += await self.repository.items_by_refs(
                flow, provider=provider, refs=refs[i : i + LOOKUP_CHUNK]
            )
        rows = {r.id: r for r in [*window_rows, *looked]}
        net = await self.repository.bank_net(flow, list(rows))

        window_items = [self.repository.to_internal(flow, r, net) for r in window_rows]
        lookup = {r.provider_ref: self.repository.to_internal(flow, r, net) for r in rows.values()}
        findings = dom.reconcile(flow=flow, window_items=window_items, lookup=lookup, external=external)

        for f in findings:
            matched = f.status == dom.RecordStatus.MATCHED
            await self.repository.add_record(
                run_id=run.id,
                flow=flow.value,
                provider=run.provider,
                provider_ref=f.provider_ref,
                status=f.status.value,
                discrepancy=f.discrepancy.value if f.discrepancy else None,
                detail=f.detail[:300],
                internal_type=_INTERNAL_TYPE[flow] if f.internal else None,
                internal_id=f.internal.id if f.internal else None,
                internal_status=f.internal.status if f.internal else None,
                internal_amount=dom.q(f.internal.amount) if f.internal else None,
                ledger_net=dom.q(f.internal.ledger_net) if f.internal else None,
                expected_ledger_net=f.expected_ledger_net,
                external_line_id=f.external.line_id if f.external else None,
                external_status=f.external.status if f.external else None,
                external_amount=dom.q(f.external.amount) if f.external else None,
                external_count=f.external_count,
                review_status=(
                    dom.ReviewStatus.NOT_REQUIRED if matched else dom.ReviewStatus.OPEN
                ).value,
            )

        counts = dom.summarize(findings)
        run.status = dom.RunStatus.COMPLETED.value
        run.completed_at = utcnow()
        run.error = None
        run.internal_count = len(window_rows)
        run.external_count = len(external)
        run.matched_count = counts["matched"]
        run.unmatched_count = counts["unmatched"]
        run.mismatch_count = counts["mismatch"]
        run.review_count = counts["requires_review"]
        await self.session.flush()

        problems = counts["unmatched"] + counts["mismatch"] + counts["requires_review"]
        await self.audit.record_system_action(
            action="RECONCILIATION_RUN_COMPLETED",
            entity_type=ENTITY_RUN,
            entity_id=str(run.id),
            new_value={"flow": flow.value, "report_date": run.report_date.isoformat(), **counts},
        )
        if problems:
            # Alert: a person must look. (Push/email alerts arrive with the
            # notification module; until then the audit trail, this log line
            # and the open-findings summary are the signal.)
            logger.warning(
                "reconciliation found %s discrepancies flow=%s date=%s run=%s",
                problems, flow.value, run.report_date, run.id,
            )
            await self.audit.record_system_action(
                action="RECONCILIATION_DISCREPANCIES_FOUND",
                entity_type=ENTITY_RUN,
                entity_id=str(run.id),
                new_value={"flow": flow.value, "report_date": run.report_date.isoformat(),
                           "discrepancies": problems},
            )
        return run

    # ------------------------------------------------------------- reads

    async def list_runs(self, *, actor_user_id, flow=None, status=None, limit=50):
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_READ)
        return await self.repository.list_runs(flow=flow, status=status, limit=min(limit, 200))

    async def get_run(self, *, actor_user_id, run_id):
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_READ)
        run = await self.repository.get_run(run_id)
        if run is None:
            raise dom.ReconciliationNotFound("Reconciliation run not found")
        return run

    async def list_records(
        self, *, actor_user_id, run_id=None, flow=None, status=None, review_status=None, limit=100
    ):
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_READ)
        return await self.repository.list_records(
            run_id=run_id, flow=flow, status=status, review_status=review_status,
            limit=min(limit, 200),
        )

    async def get_record(self, *, actor_user_id, record_id):
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_READ)
        rec = await self.repository.get_record(record_id)
        if rec is None:
            raise dom.ReconciliationNotFound("Reconciliation record not found")
        return rec

    async def open_summary(self, *, actor_user_id):
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_READ)
        return await self.repository.open_summary()

    # ------------------------------------------------------------ review

    async def _admin_id(self, actor_user_id):
        admin = await self.admin_users.get_by_user_id(actor_user_id)
        if admin is None:
            raise PermissionError("user is not an admin")
        return admin.id

    async def start_review(self, *, actor_user_id, record_id, request_id=None, ip_address=None):
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_REVIEW)
        rec = await self.repository.get_record(record_id, for_update=True)
        if rec is None:
            raise dom.ReconciliationNotFound("Reconciliation record not found")
        if rec.review_status != dom.ReviewStatus.OPEN.value:
            raise dom.ReconciliationConflict(
                "Only an open finding can be taken for review"
                if rec.review_status != dom.ReviewStatus.NOT_REQUIRED.value
                else "A matched record needs no review"
            )
        admin_id = await self._admin_id(actor_user_id)  # before changing rows (autoflush)
        rec.review_status = dom.ReviewStatus.IN_REVIEW.value
        rec.reviewed_by_admin_user_id = admin_id
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="RECONCILIATION_REVIEW_STARTED",
            entity_type=ENTITY_RECORD,
            entity_id=str(rec.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"review_status": dom.ReviewStatus.OPEN.value},
            new_value={"review_status": rec.review_status},
        )
        return rec

    async def resolve(
        self, *, actor_user_id, record_id, resolution, note, request_id=None, ip_address=None
    ):
        """Record how a finding was dealt with. This changes NOTHING about the
        payment, the payout or the ledger; it only closes the review."""
        await self._require(actor_user_id, AdminPermission.RECONCILIATION_REVIEW)
        resolution = dom.Resolution(resolution)
        note = (note or "").strip()
        if len(note) < MIN_NOTE:
            raise dom.ReconciliationError(f"A review note of at least {MIN_NOTE} characters is required")
        rec = await self.repository.get_record(record_id, for_update=True)
        if rec is None:
            raise dom.ReconciliationNotFound("Reconciliation record not found")
        if rec.review_status not in (dom.ReviewStatus.OPEN.value, dom.ReviewStatus.IN_REVIEW.value):
            raise dom.ReconciliationConflict(
                "A matched record needs no review"
                if rec.review_status == dom.ReviewStatus.NOT_REQUIRED.value
                else "This finding is already resolved"
            )
        before = rec.review_status
        admin_id = await self._admin_id(actor_user_id)  # before changing rows (autoflush)
        rec.review_status = dom.ReviewStatus.RESOLVED.value
        rec.resolution = resolution.value
        rec.review_note = note
        rec.reviewed_by_admin_user_id = admin_id
        rec.reviewed_at = utcnow()
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="RECONCILIATION_FINDING_RESOLVED",
            entity_type=ENTITY_RECORD,
            entity_id=str(rec.id),
            request_id=request_id,
            ip_address=ip_address,
            reason=note,
            old_value={"review_status": before},
            new_value={"review_status": rec.review_status, "resolution": resolution.value},
        )
        return rec
