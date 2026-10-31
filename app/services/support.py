from __future__ import annotations

import logging

from app.domain import support as dom
from app.domain.admin import AdminPermission, AdminRole, has_permission
from app.domain.repayment import today_ist, utcnow
from app.repositories.support import SupportRepository

logger = logging.getLogger(__name__)

ENTITY = "support_ticket"


class SupportService:
    """Support tickets and grievances.

    Customers see only their own tickets and only the customer-visible part of
    the history. Staff see internal notes too, but a phone number only masked;
    revealing it is a separate audited action. Sensitive tickets (fraud, personal
    data) exist only for staff with SUPPORT_MANAGE: everyone else gets "not found".
    Every state-changing or sensitive action is audited; the ticket history is
    append-only."""

    def __init__(
        self, *, session, repository: SupportRepository, admin_user_repository,
        admin_authorization_service, audit_log_service, notifications, settings,
    ):
        self.session = session
        self.repository = repository
        self.admin_users = admin_user_repository
        self.authz = admin_authorization_service
        self.audit = audit_log_service
        self.notifications = notifications
        self.settings = settings

    # -------------------------------------------------------------- helpers

    async def _event(self, ticket, event_type: dom.EventType, *, actor: dom.ActorType, admin_id=None,
                     body=None, payload=None, visibility=None):
        if visibility is None:
            visibility = dom.Visibility.CUSTOMER if event_type in dom.CUSTOMER_VISIBLE else dom.Visibility.INTERNAL
        return await self.repository.add_event(
            ticket_id=ticket.id, event_type=event_type.value, visibility=visibility.value,
            actor_type=actor.value, actor_admin_user_id=admin_id, body=body, payload=payload,
            created_at=utcnow(),
        )

    async def _notify(self, ticket, template_key: str, dedupe: str) -> None:
        await self.notifications.enqueue(
            user_id=ticket.user_id, template_key=template_key, channel="SMS",
            variables={"ticket_number": ticket.ticket_number}, dedupe_key=dedupe,
            source_type="support_ticket", source_id=ticket.id,
        )

    @staticmethod
    def _clean(text: str | None, low: int, high: int, what: str) -> str:
        text = (text or "").strip()
        if not low <= len(text) <= high:
            raise dom.SupportError(f"{what} must be {low}-{high} characters")
        return text

    # ------------------------------------------------------- customer side

    async def create_ticket(
        self, *, user_id, kind, category, subject, message, loan_application_id=None,
        loan_offer_id=None, request_id=None, ip_address=None,
    ):
        kind, category = dom.Kind(kind), dom.Category(category)
        subject = self._clean(subject, 3, 120, "The subject")
        message = self._clean(message, dom.MIN_MESSAGE, dom.MAX_MESSAGE, "The message")
        if await self.repository.count_live(user_id) >= int(self.settings.support_max_open_tickets_per_user):
            raise dom.SupportConflict("You have too many open requests; please wait for one to be resolved")
        if loan_application_id and await self.repository.application_owner(loan_application_id) != user_id:
            raise dom.SupportNotFound("Loan application not found")
        if loan_offer_id and await self.repository.offer_owner(loan_offer_id) != user_id:
            raise dom.SupportNotFound("Loan offer not found")

        now = utcnow()
        number = dom.format_ticket_number(await self.repository.next_sequence(), today_ist(now))
        ticket = await self.repository.add_ticket(
            ticket_number=number, user_id=user_id, kind=kind.value, category=category.value,
            sensitive=dom.is_sensitive(category), subject=subject, status=dom.Status.OPEN.value,
            priority=dom.Priority.HIGH.value if dom.is_sensitive(category) else dom.Priority.NORMAL.value,
            loan_application_id=loan_application_id, loan_offer_id=loan_offer_id,
            sla_due_at=dom.sla_due(kind, now, int(self.settings.support_complaint_resolution_days)),
            escalation_level=0, created_at=now,
        )
        await self._event(ticket, dom.EventType.TICKET_CREATED, actor=dom.ActorType.CUSTOMER, body=message)
        await self.audit.record_customer_action(
            actor_user_id=user_id, action="SUPPORT_TICKET_CREATED", entity_type=ENTITY, entity_id=str(ticket.id),
            request_id=request_id, ip_address=ip_address,
            new_value={"ticket_number": number, "kind": kind.value, "category": category.value},
        )
        await self._notify(ticket, "support.ticket_received", f"support_ticket:{ticket.id}:received")
        return ticket

    async def list_mine(self, *, user_id, limit=50):
        return await self.repository.list_for_user(user_id, limit=min(limit, 100))

    async def get_mine(self, *, user_id, ticket_id):
        ticket = await self.repository.get_for_user(ticket_id, user_id)
        if ticket is None:
            raise dom.SupportNotFound("Ticket not found")
        return ticket, await self.repository.list_events(ticket.id, customer_only=True)

    async def customer_reply(self, *, user_id, ticket_id, message, request_id=None, ip_address=None):
        message = self._clean(message, dom.MIN_MESSAGE, dom.MAX_MESSAGE, "The message")
        ticket = await self.repository.get_for_user(ticket_id, user_id, for_update=True)
        if ticket is None:
            raise dom.SupportNotFound("Ticket not found")
        now = utcnow()
        status = dom.Status(ticket.status)
        if not dom.customer_can_reply(status, ticket.resolved_at, now):
            raise dom.SupportConflict(
                "This request is closed; please open a new one"
                if status == dom.Status.CLOSED else "This request was resolved too long ago to reopen; please open a new one"
            )
        await self._event(ticket, dom.EventType.CUSTOMER_MESSAGE, actor=dom.ActorType.CUSTOMER, body=message)
        if status in (dom.Status.WAITING_ON_CUSTOMER, dom.Status.RESOLVED):
            ticket.status = dom.Status.IN_PROGRESS.value
            await self._event(
                ticket, dom.EventType.STATUS_CHANGED, actor=dom.ActorType.CUSTOMER,
                payload={"from": status.value, "to": dom.Status.IN_PROGRESS.value,
                         "reason": "reopened" if status == dom.Status.RESOLVED else "customer_replied"},
            )
        await self.session.flush()
        await self.audit.record_customer_action(
            actor_user_id=user_id, action="SUPPORT_CUSTOMER_MESSAGE", entity_type=ENTITY, entity_id=str(ticket.id),
            request_id=request_id, ip_address=ip_address, new_value={"reopened": status == dom.Status.RESOLVED},
        )
        return ticket

    # ------------------------------------------------------------ admin side

    async def _require(self, actor_user_id, permission):
        return await self.authz.require_permission(user_id=actor_user_id, permission=permission)

    async def _manager(self, actor_user_id) -> bool:
        return await self.authz.has_permission(user_id=actor_user_id, permission=AdminPermission.SUPPORT_MANAGE)

    async def _admin(self, actor_user_id):
        admin = await self.admin_users.get_by_user_id(actor_user_id)
        if admin is None:
            raise PermissionError("user is not an admin")
        return admin

    @staticmethod
    def _visible(ticket, manager: bool) -> None:
        if ticket is None or (ticket.sensitive and not manager):
            raise dom.SupportNotFound("Ticket not found")

    async def list_tickets(
        self, *, actor_user_id, status=None, kind=None, category=None, mine=False, unassigned=False,
        overdue=False, limit=100,
    ):
        await self._require(actor_user_id, AdminPermission.SUPPORT_READ)
        manager = await self._manager(actor_user_id)
        admin = await self._admin(actor_user_id) if mine else None
        return await self.repository.list_admin(
            include_sensitive=manager, status=status, kind=kind, category=category,
            assignee_admin_id=admin.id if admin else None, unassigned=unassigned,
            overdue_before=utcnow() if overdue else None, limit=min(limit, 200),
        )

    async def summary(self, *, actor_user_id):
        await self._require(actor_user_id, AdminPermission.SUPPORT_READ)
        return await self.repository.summary(include_sensitive=await self._manager(actor_user_id))

    async def get_ticket(self, *, actor_user_id, ticket_id, request_id=None, ip_address=None):
        await self._require(actor_user_id, AdminPermission.SUPPORT_READ)
        manager = await self._manager(actor_user_id)
        ticket = await self.repository.get(ticket_id)
        self._visible(ticket, manager)
        user = await self.repository.get_user(ticket.user_id)
        events = await self.repository.list_events(ticket.id, customer_only=False)
        if ticket.sensitive:
            await self.audit.record_admin_action(
                actor_user_id=actor_user_id, action="SUPPORT_SENSITIVE_TICKET_VIEWED", entity_type=ENTITY,
                entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
                new_value={"category": ticket.category},
            )
        return ticket, events, dom.mask_phone(user.phone_number if user else "")

    async def reveal_contact(self, *, actor_user_id, ticket_id, request_id=None, ip_address=None):
        """The customer's full phone number: needs customer-data access, is
        recorded in the ticket's internal history, and is audited."""
        await self._require(actor_user_id, AdminPermission.SUPPORT_READ)
        await self._require(actor_user_id, AdminPermission.CUSTOMER_READ)
        manager = await self._manager(actor_user_id)
        admin = await self._admin(actor_user_id)
        ticket = await self.repository.get(ticket_id)
        self._visible(ticket, manager)
        user = await self.repository.get_user(ticket.user_id)
        await self._event(ticket, dom.EventType.CONTACT_REVEALED, actor=dom.ActorType.ADMIN, admin_id=admin.id,
                          payload={"field": "phone_number"})
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_CONTACT_REVEALED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
            new_value={"field": "phone_number"},
        )
        return user.phone_number

    async def _workable(self, actor_user_id, ticket_id, *, request_id=None, ip_address=None):
        """Lock a live ticket the actor may act on. An unassigned ticket is
        claimed by whoever first works it; one assigned to someone else is off
        limits to agents (managers may act on any)."""
        await self._require(actor_user_id, AdminPermission.SUPPORT_UPDATE)
        manager = await self._manager(actor_user_id)
        admin = await self._admin(actor_user_id)
        ticket = await self.repository.get(ticket_id, for_update=True)
        self._visible(ticket, manager)
        if ticket.status == dom.Status.CLOSED.value:
            raise dom.SupportConflict("This ticket is closed")
        if ticket.assigned_to_admin_user_id is None:
            await self._set_assignee(ticket, admin.id, admin.id, actor_user_id, request_id, ip_address)
        elif ticket.assigned_to_admin_user_id != admin.id and not manager:
            raise PermissionError("ticket is assigned to someone else")
        return ticket, admin

    async def _set_assignee(self, ticket, target_id, by_admin_id, actor_user_id, request_id, ip_address):
        before = ticket.assigned_to_admin_user_id
        ticket.assigned_to_admin_user_id = target_id
        ticket.assigned_at = utcnow()
        await self._event(
            ticket, dom.EventType.ASSIGNED, actor=dom.ActorType.ADMIN, admin_id=by_admin_id,
            payload={"from": str(before) if before else None, "to": str(target_id)},
        )
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_TICKET_ASSIGNED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
            old_value={"assignee": str(before) if before else None}, new_value={"assignee": str(target_id)},
        )

    async def assign(self, *, actor_user_id, ticket_id, assignee_admin_id=None, request_id=None, ip_address=None):
        await self._require(actor_user_id, AdminPermission.SUPPORT_UPDATE)
        manager = await self._manager(actor_user_id)
        me = await self._admin(actor_user_id)
        ticket = await self.repository.get(ticket_id, for_update=True)
        self._visible(ticket, manager)
        if ticket.status == dom.Status.CLOSED.value:
            raise dom.SupportConflict("This ticket is closed")
        target_id = assignee_admin_id or me.id
        if target_id != me.id:
            await self._require(actor_user_id, AdminPermission.SUPPORT_MANAGE)
            target = await self.repository.get_admin(target_id)
            try:
                ok = bool(target and target.is_active and has_permission(
                    AdminRole(target.role), AdminPermission.SUPPORT_UPDATE))
            except ValueError:
                ok = False
            if not ok:
                raise dom.SupportError("That admin cannot take tickets")
        elif ticket.assigned_to_admin_user_id not in (None, me.id) and not manager:
            raise dom.SupportConflict("This ticket is already assigned to someone else")
        if ticket.assigned_to_admin_user_id == target_id:
            return ticket
        await self._set_assignee(ticket, target_id, me.id, actor_user_id, request_id, ip_address)
        return ticket

    async def reply(self, *, actor_user_id, ticket_id, message, request_id=None, ip_address=None):
        message = self._clean(message, dom.MIN_MESSAGE, dom.MAX_MESSAGE, "The reply")
        ticket, admin = await self._workable(actor_user_id, ticket_id, request_id=request_id, ip_address=ip_address)
        now = utcnow()
        event = await self._event(ticket, dom.EventType.AGENT_REPLY, actor=dom.ActorType.ADMIN,
                                  admin_id=admin.id, body=message)
        if ticket.first_response_at is None:
            ticket.first_response_at = now
        if ticket.status == dom.Status.OPEN.value:
            ticket.status = dom.Status.IN_PROGRESS.value
            await self._event(ticket, dom.EventType.STATUS_CHANGED, actor=dom.ActorType.ADMIN, admin_id=admin.id,
                              payload={"from": "OPEN", "to": "IN_PROGRESS"})
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_AGENT_REPLIED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
        )
        await self._notify(ticket, "support.ticket_replied", f"support_ticket_event:{event.id}")
        return ticket

    async def add_note(self, *, actor_user_id, ticket_id, note, request_id=None, ip_address=None):
        note = self._clean(note, dom.MIN_NOTE, dom.MAX_MESSAGE, "The note")
        ticket, admin = await self._workable(actor_user_id, ticket_id, request_id=request_id, ip_address=ip_address)
        await self._event(ticket, dom.EventType.INTERNAL_NOTE, actor=dom.ActorType.ADMIN,
                          admin_id=admin.id, body=note)
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_INTERNAL_NOTE_ADDED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
        )
        return ticket

    async def change_status(self, *, actor_user_id, ticket_id, new_status, note=None, request_id=None, ip_address=None):
        new = dom.Status(new_status)
        ticket, admin = await self._workable(actor_user_id, ticket_id, request_id=request_id, ip_address=ip_address)
        current = dom.Status(ticket.status)
        if not dom.can_transition(current, new):
            raise dom.SupportConflict(f"A ticket cannot go from {current.value} to {new.value}")
        note = (note or "").strip()
        if new == dom.Status.RESOLVED and len(note) < dom.MIN_REASON:
            raise dom.SupportError(f"A resolution message of at least {dom.MIN_REASON} characters is required")
        now = utcnow()
        ticket.status = new.value
        if new == dom.Status.RESOLVED:
            ticket.resolved_at = now
        if new == dom.Status.CLOSED:
            ticket.closed_at = now
        await self._event(ticket, dom.EventType.STATUS_CHANGED, actor=dom.ActorType.ADMIN, admin_id=admin.id,
                          payload={"from": current.value, "to": new.value})
        resolution_event = None
        if new == dom.Status.RESOLVED:  # the resolution is what the customer reads
            resolution_event = await self._event(
                ticket, dom.EventType.AGENT_REPLY, actor=dom.ActorType.ADMIN, admin_id=admin.id, body=note)
        elif note:
            await self._event(ticket, dom.EventType.INTERNAL_NOTE, actor=dom.ActorType.ADMIN,
                              admin_id=admin.id, body=note)
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_TICKET_STATUS_CHANGED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
            old_value={"status": current.value}, new_value={"status": new.value},
        )
        if resolution_event is not None:
            await self._notify(ticket, "support.ticket_resolved", f"support_ticket:{ticket.id}:resolved:{resolution_event.id}")
        return ticket

    async def set_priority(self, *, actor_user_id, ticket_id, priority, request_id=None, ip_address=None):
        priority = dom.Priority(priority)
        ticket, admin = await self._workable(actor_user_id, ticket_id, request_id=request_id, ip_address=ip_address)
        before = ticket.priority
        if before == priority.value:
            return ticket
        ticket.priority = priority.value
        await self._event(ticket, dom.EventType.PRIORITY_CHANGED, actor=dom.ActorType.ADMIN, admin_id=admin.id,
                          payload={"from": before, "to": priority.value})
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_TICKET_PRIORITY_CHANGED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address,
            old_value={"priority": before}, new_value={"priority": priority.value},
        )
        return ticket

    async def escalate(self, *, actor_user_id, ticket_id, reason, request_id=None, ip_address=None):
        reason = self._clean(reason, dom.MIN_REASON, dom.MAX_MESSAGE, "The escalation reason")
        await self._require(actor_user_id, AdminPermission.SUPPORT_MANAGE)
        ticket, admin = await self._workable(actor_user_id, ticket_id, request_id=request_id, ip_address=ip_address)
        if ticket.kind != dom.Kind.COMPLAINT.value:
            raise dom.SupportConflict("Only complaints are escalated")
        if ticket.escalation_level >= dom.MAX_ESCALATION_LEVEL:
            raise dom.SupportConflict("The complaint is already at the highest escalation level")
        before = ticket.escalation_level
        ticket.escalation_level = before + 1
        await self._event(ticket, dom.EventType.ESCALATED, actor=dom.ActorType.ADMIN, admin_id=admin.id,
                          body=reason, payload={"from_level": before, "to_level": before + 1})
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="SUPPORT_COMPLAINT_ESCALATED", entity_type=ENTITY,
            entity_id=str(ticket.id), request_id=request_id, ip_address=ip_address, reason=reason,
            old_value={"level": before}, new_value={"level": before + 1},
        )
        return ticket

    def is_overdue(self, ticket) -> bool:
        return dom.is_overdue(dom.Status(ticket.status), ticket.sla_due_at, utcnow())
