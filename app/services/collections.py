from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.domain import collections as dom
from app.domain.admin import AdminPermission, AdminRole, has_permission
from app.domain.repayment import today_ist, utcnow
from app.repositories.collection import CollectionRepository
from app.repositories.repayment import RepaymentRepository

logger = logging.getLogger(__name__)

ENTITY = "collection_case"
MIN_NOTE = 3
MAX_NOTE = 2000


@dataclass(frozen=True)
class SyncResult:
    action: str  # opened | updated | unchanged | closed | none
    case_id: UUID | None = None


class CollectionService:
    """Overdue cases, their history, and the reminder/escalation workflow.

    Workers (DPD sync, reminders, escalation) are safe to run repeatedly and
    from several instances: every step locks the schedule or case first (the
    same order payments use: schedule, then case), changes only what is out of
    date, and creates reminders/escalations through a per-case dedupe key the
    database enforces. Nothing here contacts a customer; a reminder is a
    recorded request that the notification module turns into a message.

    Promise-to-pay is deliberately NOT built: it needs an approved collections
    process (who may grant one, for how long, what it suspends)."""

    def __init__(
        self, *, session, repository: CollectionRepository, schedules: RepaymentRepository,
        admin_user_repository, admin_authorization_service, audit_log_service, settings,
    ):
        self.session = session
        self.repository = repository
        self.schedules = schedules
        self.admin_users = admin_user_repository
        self.authz = admin_authorization_service
        self.audit = audit_log_service
        self.settings = settings

    # ------------------------------------------------------------- helpers

    async def _event(self, case, event_type: dom.EventType, *, admin_id=None, **fields) -> bool:
        return await self.repository.add_event(
            case_id=case.id,
            event_type=event_type.value,
            actor_type=(dom.ActorType.ADMIN if admin_id else dom.ActorType.SYSTEM).value,
            actor_admin_user_id=admin_id,
            created_at=utcnow(),
            **fields,
        )

    # --------------------------------------------------------- DPD sync

    async def sync_candidates(self, *, limit: int | None = None, today: date | None = None):
        """Schedules to look at: overdue ones, plus those with a live case
        (which may have been paid up and need closing)."""
        limit = limit or int(self.settings.collections_batch_size)
        today = today or today_ist()
        seen: dict[UUID, None] = {}
        for sid in await self.repository.overdue_schedule_ids(today=today, limit=limit):
            seen[sid] = None
        for sid in await self.repository.live_case_schedule_ids(limit=limit):
            seen[sid] = None
        return list(seen)[:limit]

    async def sync_schedule(self, schedule_id, *, today: date | None = None) -> SyncResult:
        today = today or today_ist()
        schedule = await self.schedules.get_schedule(schedule_id, for_update=True)
        if schedule is None:
            return SyncResult("none")
        case = await self.repository.get_live_case(schedule.id, for_update=True)

        overdue = None
        if schedule.status == "ACTIVE":
            views = [
                dom.InstallmentView(
                    id=i.id,
                    number=i.installment_number,
                    due_date=i.due_date,
                    principal_outstanding=Decimal(i.principal_due - i.principal_paid),
                    interest_outstanding=Decimal(i.interest_due - i.interest_paid),
                    fee_outstanding=Decimal(i.fee_due - i.fee_paid),
                )
                for i in await self.schedules.list_installments(schedule.id)
            ]
            overdue = dom.overdue_of(views, today)

        if overdue is None:
            if case is None:
                return SyncResult("none")
            reason = dom.CloseReason.CURED if schedule.status == "ACTIVE" else dom.CloseReason.LOAN_INACTIVE
            await self._close(case, reason)
            return SyncResult("closed", case.id)

        bucket = dom.bucket_for(overdue.dpd)
        if case is None:
            case_id = await self.repository.insert_case(
                user_id=schedule.user_id,
                loan_offer_id=schedule.loan_offer_id,
                schedule_id=schedule.id,
                oldest_installment_id=overdue.oldest_installment_id,
                status=dom.CaseStatus.OPEN.value,
                dpd=overdue.dpd,
                dpd_bucket=bucket,
                overdue_principal=overdue.principal,
                overdue_interest=overdue.interest,
                overdue_fees=overdue.fees,
                escalation_level=0,
            )
            if case_id is None:  # another worker opened it first
                return SyncResult("none")
            case = await self.repository.get_case(case_id, for_update=True)
            await self._event(
                case, dom.EventType.CASE_OPENED, installment_id=overdue.oldest_installment_id,
                payload={"dpd": overdue.dpd, "bucket": bucket, "overdue_total": str(overdue.total)},
            )
            await self.audit.record_system_action(
                action="COLLECTION_CASE_OPENED", entity_type=ENTITY, entity_id=str(case.id),
                new_value={"dpd": overdue.dpd, "overdue_total": str(overdue.total)},
                event_metadata={"loan_offer_id": str(schedule.loan_offer_id)},
            )
            return SyncResult("opened", case.id)

        old_bucket = case.dpd_bucket
        new_values = {
            "oldest_installment_id": overdue.oldest_installment_id,
            "dpd": overdue.dpd,
            "dpd_bucket": bucket,
            "overdue_principal": overdue.principal,
            "overdue_interest": overdue.interest,
            "overdue_fees": overdue.fees,
        }
        changed = False
        for name, value in new_values.items():
            if getattr(case, name) != value:
                setattr(case, name, value)
                changed = True
        if not changed:
            return SyncResult("unchanged", case.id)
        if old_bucket != bucket:
            await self._event(
                case, dom.EventType.BUCKET_CHANGED, installment_id=overdue.oldest_installment_id,
                payload={"from": old_bucket, "to": bucket, "dpd": overdue.dpd},
            )
        await self.session.flush()
        return SyncResult("updated", case.id)

    async def _close(self, case, reason: dom.CloseReason) -> None:
        case.status = dom.CaseStatus.CLOSED.value
        case.close_reason = reason.value
        case.closed_at = utcnow()
        case.next_action = None
        case.next_action_at = None
        await self._event(case, dom.EventType.CASE_CLOSED, payload={"reason": reason.value, "last_dpd": case.dpd})
        await self.session.flush()
        await self.audit.record_system_action(
            action="COLLECTION_CASE_CLOSED", entity_type=ENTITY, entity_id=str(case.id),
            new_value={"reason": reason.value},
        )

    # ------------------------------------------------------- reminders

    async def reminder_candidates(self, *, limit: int | None = None):
        if not self.settings.collections_reminders_enabled:
            return []
        return await self.repository.reminder_case_ids(
            limit=limit or int(self.settings.collections_batch_size)
        )

    async def schedule_reminders(self, case_id) -> int:
        """Create the reminder requests due for the case's current DPD.
        Returns how many NEW ones were created (0 when repeated)."""
        if not self.settings.collections_reminders_enabled:
            return 0
        case = await self.repository.get_case(case_id, for_update=True)
        if case is None or case.status == dom.CaseStatus.CLOSED.value or case.dpd < 1:
            return 0
        milestone = dom.due_reminder_milestone(case.dpd)
        if milestone is None:
            return 0
        created = 0
        for channel in dom.REMINDER_MILESTONES[milestone]:
            made = await self._event(
                case, dom.EventType.REMINDER_SCHEDULED,
                installment_id=case.oldest_installment_id,
                dedupe_key=dom.reminder_key(case.oldest_installment_id, milestone, channel),
                channel=channel.value,
                template_key=f"collections.dpd_{milestone}.{channel.value.lower()}",
                payload={
                    "dpd": case.dpd, "milestone": milestone, "bucket": case.dpd_bucket,
                    "overdue_total": str(case.overdue_principal + case.overdue_interest + case.overdue_fees),
                },
            )
            created += int(made)
        if created:
            case.last_reminder_at = utcnow()
            await self.session.flush()
        return created

    # ------------------------------------------------------ escalation

    async def escalation_candidates(self, *, limit: int | None = None):
        if not self.settings.collections_escalation_enabled:
            return []
        return await self.repository.escalation_case_ids(
            min_dpd=min(dom.ESCALATION_THRESHOLDS.values()),
            max_level=dom.MAX_LEVEL,
            limit=limit or int(self.settings.collections_batch_size),
        )

    async def escalate_case(self, case_id) -> int | None:
        """Raise the case to the level its DPD calls for. Returns the new
        level, or None when nothing was due. Levels only ever go up."""
        if not self.settings.collections_escalation_enabled:
            return None
        case = await self.repository.get_case(case_id, for_update=True)
        if case is None or case.status == dom.CaseStatus.CLOSED.value:
            return None
        target = dom.escalation_level_for(case.dpd)
        if target <= case.escalation_level:
            return None
        before = case.escalation_level
        case.escalation_level = target
        case.status = dom.CaseStatus.ESCALATED.value
        case.next_action = dom.NextAction.ESCALATION_REVIEW.value
        case.next_action_at = utcnow()
        await self._event(
            case, dom.EventType.ESCALATED, installment_id=case.oldest_installment_id,
            dedupe_key=dom.escalation_key(case.oldest_installment_id, target),
            payload={"from_level": before, "to_level": target, "dpd": case.dpd, "reason": "DPD_THRESHOLD"},
        )
        await self.session.flush()
        await self.audit.record_system_action(
            action="COLLECTION_CASE_ESCALATED", entity_type=ENTITY, entity_id=str(case.id),
            old_value={"level": before}, new_value={"level": target, "dpd": case.dpd},
        )
        return target

    # ----------------------------------------------------- admin reads

    async def _require(self, actor_user_id, permission: AdminPermission):
        return await self.authz.require_permission(user_id=actor_user_id, permission=permission)

    async def _admin(self, actor_user_id):
        admin = await self.admin_users.get_by_user_id(actor_user_id)
        if admin is None:
            raise PermissionError("user is not an admin")
        return admin

    async def list_cases(
        self, *, actor_user_id, status=None, bucket=None, mine=False, unassigned=False,
        min_dpd=None, limit=100,
    ):
        await self._require(actor_user_id, AdminPermission.COLLECTIONS_READ)
        if bucket is not None and bucket not in dom.BUCKET_LABELS:
            raise dom.CollectionsError("Unknown bucket")
        admin = await self._admin(actor_user_id) if mine else None
        return await self.repository.list_cases(
            status=status, bucket=bucket, assignee_admin_id=admin.id if admin else None,
            unassigned=unassigned, min_dpd=min_dpd, limit=min(limit, 200),
        )

    async def get_case(self, *, actor_user_id, case_id):
        await self._require(actor_user_id, AdminPermission.COLLECTIONS_READ)
        case = await self.repository.get_case(case_id)
        if case is None:
            raise dom.CollectionsNotFound("Collection case not found")
        return case, await self.repository.list_events(case.id)

    async def summary(self, *, actor_user_id):
        await self._require(actor_user_id, AdminPermission.COLLECTIONS_READ)
        return await self.repository.summary()

    # ----------------------------------------------------- admin writes

    async def _workable(self, actor_user_id, case_id):
        """Lock a live case the actor may act on: managers on any, agents only
        on cases assigned to them."""
        await self._require(actor_user_id, AdminPermission.COLLECTIONS_UPDATE)
        admin = await self._admin(actor_user_id)
        case = await self.repository.get_case(case_id, for_update=True)
        if case is None:
            raise dom.CollectionsNotFound("Collection case not found")
        if case.status == dom.CaseStatus.CLOSED.value:
            raise dom.CollectionsConflict("This case is closed")
        manager = await self.authz.has_permission(
            user_id=actor_user_id, permission=AdminPermission.COLLECTIONS_MANAGE
        )
        if not manager and case.assigned_to_admin_user_id != admin.id:
            raise PermissionError("case is not assigned to this agent")
        return case, admin

    @staticmethod
    def _worked(case) -> None:
        if case.status == dom.CaseStatus.OPEN.value:
            case.status = dom.CaseStatus.IN_PROGRESS.value

    async def assign(self, *, actor_user_id, case_id, assignee_admin_id=None, request_id=None, ip_address=None):
        await self._require(actor_user_id, AdminPermission.COLLECTIONS_UPDATE)
        me = await self._admin(actor_user_id)
        case = await self.repository.get_case(case_id, for_update=True)
        if case is None:
            raise dom.CollectionsNotFound("Collection case not found")
        if case.status == dom.CaseStatus.CLOSED.value:
            raise dom.CollectionsConflict("This case is closed")

        target_id = assignee_admin_id or me.id
        if target_id != me.id:
            await self._require(actor_user_id, AdminPermission.COLLECTIONS_MANAGE)
            target = await self.repository.get_admin(target_id)
            if target is None or not target.is_active:
                raise dom.CollectionsError("That admin cannot take cases")
            try:
                role_ok = has_permission(AdminRole(target.role), AdminPermission.COLLECTIONS_UPDATE)
            except ValueError:
                role_ok = False
            if not role_ok:
                raise dom.CollectionsError("That admin cannot take cases")
        elif case.assigned_to_admin_user_id not in (None, me.id):
            manager = await self.authz.has_permission(
                user_id=actor_user_id, permission=AdminPermission.COLLECTIONS_MANAGE
            )
            if not manager:
                raise dom.CollectionsConflict("This case is already assigned to someone else")

        if case.assigned_to_admin_user_id == target_id:
            return case  # already theirs: nothing to do
        before = case.assigned_to_admin_user_id
        case.assigned_to_admin_user_id = target_id
        case.assigned_at = utcnow()
        await self._event(
            case, dom.EventType.ASSIGNED, admin_id=me.id,
            payload={"from": str(before) if before else None, "to": str(target_id)},
        )
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="COLLECTION_CASE_ASSIGNED", entity_type=ENTITY,
            entity_id=str(case.id), request_id=request_id, ip_address=ip_address,
            old_value={"assignee": str(before) if before else None}, new_value={"assignee": str(target_id)},
        )
        return case

    async def add_note(self, *, actor_user_id, case_id, note, request_id=None, ip_address=None):
        note = (note or "").strip()
        if not MIN_NOTE <= len(note) <= MAX_NOTE:
            raise dom.CollectionsError(f"A note must be {MIN_NOTE}-{MAX_NOTE} characters")
        case, admin = await self._workable(actor_user_id, case_id)
        self._worked(case)
        await self._event(case, dom.EventType.NOTE_ADDED, admin_id=admin.id, note=note)
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="COLLECTION_NOTE_ADDED", entity_type=ENTITY,
            entity_id=str(case.id), request_id=request_id, ip_address=ip_address,
        )
        return case

    async def log_contact(self, *, actor_user_id, case_id, channel, outcome, note=None, request_id=None, ip_address=None):
        channel = dom.Channel(channel)
        outcome = dom.ContactOutcome(outcome)
        case, admin = await self._workable(actor_user_id, case_id)
        self._worked(case)
        case.last_contact_at = utcnow()
        await self._event(
            case, dom.EventType.CONTACT_ATTEMPT, admin_id=admin.id, channel=channel.value,
            note=(note or "").strip() or None, payload={"outcome": outcome.value},
        )
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="COLLECTION_CONTACT_LOGGED", entity_type=ENTITY,
            entity_id=str(case.id), request_id=request_id, ip_address=ip_address,
            new_value={"channel": channel.value, "outcome": outcome.value},
        )
        return case

    async def set_next_action(self, *, actor_user_id, case_id, action, due_at: datetime, note=None, request_id=None, ip_address=None):
        action = dom.NextAction(action)
        if due_at.tzinfo is None:
            raise dom.CollectionsError("The follow-up time must include a time zone")
        if due_at <= utcnow():
            raise dom.CollectionsError("The follow-up time must be in the future")
        if due_at > utcnow() + timedelta(days=90):
            raise dom.CollectionsError("The follow-up time is too far ahead")
        case, admin = await self._workable(actor_user_id, case_id)
        self._worked(case)
        case.next_action = action.value
        case.next_action_at = due_at
        await self._event(
            case, dom.EventType.NEXT_ACTION_SET, admin_id=admin.id,
            note=(note or "").strip() or None,
            payload={"action": action.value, "due_at": due_at.isoformat()},
        )
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="COLLECTION_NEXT_ACTION_SET", entity_type=ENTITY,
            entity_id=str(case.id), request_id=request_id, ip_address=ip_address,
            new_value={"action": action.value, "due_at": due_at.isoformat()},
        )
        return case

    async def escalate_manually(self, *, actor_user_id, case_id, reason, request_id=None, ip_address=None):
        reason = (reason or "").strip()
        if len(reason) < 10:
            raise dom.CollectionsError("An escalation reason of at least 10 characters is required")
        await self._require(actor_user_id, AdminPermission.COLLECTIONS_MANAGE)
        case, admin = await self._workable(actor_user_id, case_id)
        if case.escalation_level >= dom.MAX_LEVEL:
            raise dom.CollectionsConflict("The case is already at the highest escalation level")
        before = case.escalation_level
        case.escalation_level = before + 1
        case.status = dom.CaseStatus.ESCALATED.value
        case.next_action = dom.NextAction.ESCALATION_REVIEW.value
        case.next_action_at = utcnow()
        await self._event(
            case, dom.EventType.ESCALATED, admin_id=admin.id, note=reason,
            payload={"from_level": before, "to_level": case.escalation_level, "manual": True},
        )
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="COLLECTION_CASE_ESCALATED_MANUALLY", entity_type=ENTITY,
            entity_id=str(case.id), request_id=request_id, ip_address=ip_address, reason=reason,
            old_value={"level": before}, new_value={"level": case.escalation_level},
        )
        return case
