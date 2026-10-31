from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.domain import notifications as dom
from app.domain.admin import AdminPermission
from app.domain.repayment import utcnow
from app.providers.notification import (
    NotificationCallbackMalformed,
    NotificationPermanent,
    NotificationTransient,
)
from app.repositories.notification import NotificationRepository

logger = logging.getLogger(__name__)

ENTITY_TEMPLATE = "notification_template"
ENTITY = "notification"
MIN_REASON = 10


@dataclass(frozen=True)
class EnqueueResult:
    notification_id: UUID
    created: bool  # False: the dedupe key already existed, nothing new was made
    status: str


@dataclass(frozen=True)
class ReceiptResult:
    outcome: str


class NotificationService:
    """Creates, sends and tracks customer notifications.

    Sending is asynchronous: enqueue() only records a row; a worker later
    claims due rows (committed before the provider is called), sends with the
    notification's own idempotency key, and records the outcome. Transient
    failures retry with backoff up to a limit, then the notification is
    dead-lettered for a person. A message that must exist once carries a
    dedupe key the database enforces."""

    def __init__(
        self, *, session, repository: NotificationRepository, admin_user_repository,
        admin_authorization_service, audit_log_service, provider, settings,
    ):
        self.session = session
        self.repository = repository
        self.admin_users = admin_user_repository
        self.authz = admin_authorization_service
        self.audit = audit_log_service
        self.provider = provider
        self.settings = settings

    # ------------------------------------------------------------ helpers

    async def _require(self, actor_user_id, permission: AdminPermission):
        return await self.authz.require_permission(user_id=actor_user_id, permission=permission)

    async def _admin_id(self, actor_user_id):
        admin = await self.admin_users.get_by_user_id(actor_user_id)
        if admin is None:
            raise PermissionError("user is not an admin")
        return admin.id

    @staticmethod
    def _destination(user, channel: str) -> str | None:
        """SMS goes to the customer's OTP-verified phone. Email and push need
        a verified address / registered device, which does not exist yet, so
        those customers are ineligible rather than guessed at."""
        if channel == dom.Channel.SMS.value:
            return user.phone_number
        return None

    async def _eligible(self, user, category: dom.Category, channel: str) -> dom.Eligibility:
        pref = None
        if category != dom.Category.TRANSACTIONAL:
            pref = await self.repository.preference(user.id, category.value, channel)
        return dom.eligibility(
            category=category,
            user_active=bool(user and user.status == "active"),
            has_destination=bool(self._destination(user, channel)),
            preference=pref,
        )

    # ------------------------------------------------------------ enqueue

    async def enqueue(
        self, *, user_id, template_key: str, channel, variables: dict | None = None,
        dedupe_key: str | None = None, source_type: str | None = None, source_id=None,
    ) -> EnqueueResult:
        channel = dom.Channel(channel).value
        category = dom.category_for_key(template_key)
        if category in (dom.Category.TRANSACTIONAL, dom.Category.COLLECTIONS) and not dedupe_key:
            raise dom.NotificationError(
                "Transactional and collections messages need a dedupe key so they are sent once"
            )
        if dedupe_key:
            existing = await self.repository.get_by_dedupe(dedupe_key)
            if existing is not None:
                return EnqueueResult(existing.id, False, existing.status)
        user = await self.repository.get_user(user_id)
        if user is None:
            raise dom.NotificationNotFound("User not found")

        template = await self.repository.approved_template(template_key, channel)
        clean: dict = {}
        status, reason, version = dom.Status.PENDING, None, None
        if template is None:
            status, reason = dom.Status.SUPPRESSED, dom.Suppression.NO_APPROVED_TEMPLATE
        else:
            version = template.version
            try:
                clean = dom.clean_variables(variables or {}, list(template.allowed_variables))
                dom.render(template.body, clean)  # every placeholder must be filled
            except dom.NotificationError:
                status, reason, clean = dom.Status.SUPPRESSED, dom.Suppression.BAD_VARIABLES, {}
        if status == dom.Status.PENDING:
            decision = await self._eligible(user, category, channel)
            if not decision.ok:
                status, reason = dom.Status.SUPPRESSED, decision.reason

        nid = await self.repository.insert(
            user_id=user.id, template_key=template_key, template_version=version, channel=channel,
            category=category.value, variables=clean, dedupe_key=dedupe_key, source_type=source_type,
            source_id=source_id, status=status.value, attempts=0,
            max_attempts=int(self.settings.notification_max_attempts), next_attempt_at=utcnow(),
            suppress_reason=reason.value if reason else None,
        )
        if nid is None:  # lost a race on the dedupe key
            existing = await self.repository.get_by_dedupe(dedupe_key)
            return EnqueueResult(existing.id, False, existing.status)
        return EnqueueResult(nid, True, status.value)

    async def intake_collection_reminders(self, *, limit: int | None = None) -> int:
        """Turn collection reminder requests (2.15) into notifications."""
        made = 0
        for event, user_id in await self.repository.reminders_without_notification(
            limit=limit or int(self.settings.notification_batch_size)
        ):
            payload = event.payload or {}
            res = await self.enqueue(
                user_id=user_id,
                template_key=event.template_key,
                channel=event.channel,
                variables={"dpd": payload.get("dpd", ""), "overdue_total": payload.get("overdue_total", "")},
                dedupe_key=f"collection_event:{event.id}",
                source_type="collection_event",
                source_id=event.id,
            )
            made += int(res.created)
        return made

    # ------------------------------------------------------------- sending

    async def claim_due(self, *, limit: int | None = None) -> list[UUID]:
        """Mark due notifications SENDING (the caller commits before sending).
        A row whose sender crashed (lease expired) is retried, or dead-lettered
        if it has already used all its attempts."""
        now = utcnow()
        claimed: list[UUID] = []
        rows = await self.repository.claim_due(
            now=now, lease=dom.LEASE, limit=limit or int(self.settings.notification_batch_size)
        )
        for n in rows:
            if n.status == dom.Status.SENDING.value:  # crashed sender
                await self.repository.add_attempt(
                    notification_id=n.id, attempt_no=n.attempts, outcome="LEASE_EXPIRED"
                )
                if n.attempts >= n.max_attempts:
                    self._dead(n, "LEASE_EXPIRED", now)
                    continue
            n.status = dom.Status.SENDING.value
            n.attempts += 1
            n.locked_at = now
            claimed.append(n.id)
        await self.session.flush()
        return claimed

    @staticmethod
    def _dead(n, code: str, now) -> None:
        n.status = dom.Status.DEAD.value
        n.failure_code = code
        n.dead_at = now
        n.locked_at = None

    async def send_one(self, notification_id) -> str:
        """Send one claimed notification and record the outcome. Returns the
        resulting status. The provider call is idempotent on the key, so a
        retry after a timeout cannot deliver twice."""
        n = await self.repository.get(notification_id)
        if n is None or n.status != dom.Status.SENDING.value:
            return n.status if n else "MISSING"
        attempt_no = n.attempts
        now = utcnow()

        # Re-check at send time: the customer may have opted out since.
        user = await self.repository.get_user(n.user_id)
        category = dom.Category(n.category)
        decision = await self._eligible(user, category, n.channel) if user else dom.Eligibility(
            False, dom.Suppression.USER_NOT_ACTIVE)
        template = await self.repository.approved_template(n.template_key, n.channel, version=n.template_version)
        if not decision.ok or template is None:
            reason = decision.reason or dom.Suppression.NO_APPROVED_TEMPLATE
            return await self._finish(n, attempt_no, "SUPPRESS", code=reason.value)

        try:
            body = dom.render(template.body, dict(n.variables))
        except dom.NotificationError:
            return await self._finish(n, attempt_no, "SUPPRESS", code=dom.Suppression.BAD_VARIABLES.value)

        try:
            result = await self.provider.send(
                channel=n.channel, destination=self._destination(user, n.channel), body=body,
                subject=template.subject, idempotency_key=f"notification:{n.id}",
            )
        except NotificationPermanent as exc:
            return await self._finish(n, attempt_no, "PERMANENT", code=exc.code)
        except NotificationTransient:
            return await self._finish(n, attempt_no, "TRANSIENT", code="PROVIDER_UNAVAILABLE")
        return await self._finish(n, attempt_no, "SENT", provider_ref=result.provider_ref, now=now)

    async def _finish(self, n, attempt_no, kind: str, *, code=None, provider_ref=None, now=None) -> str:
        """Record the result under the row lock, only if this send still owns the row."""
        n = await self.repository.get(n.id, for_update=True)
        if n.status != dom.Status.SENDING.value or n.attempts != attempt_no:
            return n.status  # reclaimed or finished by someone else meanwhile
        now = now or utcnow()
        n.locked_at = None
        if kind == "SENT":
            n.status = dom.Status.SENT.value
            n.provider = self.provider.name
            n.provider_ref = provider_ref
            n.sent_at = now
            n.failure_code = None
            outcome = "SENT"
        elif kind == "SUPPRESS":
            # not sent on purpose: ends the notification without an attempt
            n.status = dom.Status.SUPPRESSED.value
            n.suppress_reason = code
            outcome = None
        elif kind == "PERMANENT":
            self._dead(n, code or "PROVIDER_REJECTED", now)
            outcome = "PERMANENT_FAILURE"
        else:  # transient
            outcome = "TRANSIENT_FAILURE"
            n.failure_code = code
            if n.attempts >= n.max_attempts:
                self._dead(n, "RETRIES_EXHAUSTED", now)
            else:
                n.status = dom.Status.PENDING.value
                n.next_attempt_at = now + dom.backoff_for(n.attempts)
        if outcome:
            await self.repository.add_attempt(
                notification_id=n.id, attempt_no=attempt_no, outcome=outcome, failure_code=code
            )
        await self.session.flush()
        if n.status == dom.Status.DEAD.value:
            logger.warning("notification dead-lettered id=%s code=%s", n.id, n.failure_code)
            await self.audit.record_system_action(
                action="NOTIFICATION_DEAD_LETTERED", entity_type=ENTITY, entity_id=str(n.id),
                new_value={"code": n.failure_code, "attempts": n.attempts, "channel": n.channel,
                           "template_key": n.template_key},
            )
        return n.status

    # ------------------------------------------------------------ receipts

    async def handle_receipt(self, *, provider_name: str, headers, body: bytes) -> ReceiptResult:
        if provider_name.lower() != self.provider.name:
            raise NotificationCallbackMalformed("unknown provider")
        receipt = self.provider.verify_webhook(headers=headers, body=body)  # may raise
        event_id = await self.repository.insert_event(
            provider=self.provider.name, provider_event_id=receipt.event_id,
            provider_ref=receipt.provider_ref, reported_status=receipt.status,
        )
        if event_id is None:
            return ReceiptResult("DUPLICATE")
        n = await self.repository.get_by_provider_ref(self.provider.name, receipt.provider_ref, for_update=True)
        if n is None:
            await self.repository.set_event_outcome(event_id, "UNKNOWN_REFERENCE")
            return ReceiptResult("UNKNOWN_REFERENCE")
        if n.status != dom.Status.SENT.value:
            outcome = "IGNORED"  # already delivered/failed (or never sent): first word stands
        elif receipt.status == "DELIVERED":
            n.status = dom.Status.DELIVERED.value
            n.delivered_at = receipt.occurred_at or utcnow()
            outcome = "DELIVERED"
        else:
            n.status = dom.Status.DELIVERY_FAILED.value
            n.failure_code = receipt.failure_code or "DELIVERY_FAILED"
            outcome = "DELIVERY_FAILED"
        await self.repository.set_event_outcome(event_id, outcome)
        await self.session.flush()
        return ReceiptResult(outcome)

    # ------------------------------------------------------- customer side

    async def my_notifications(self, *, user_id, limit=50):
        return await self.repository.list(user_id=user_id, limit=min(limit, 100))

    async def my_preferences(self, *, user_id) -> list[dict]:
        """Every choosable category x channel with the current effective setting."""
        stored = {(p.category, p.channel): p.enabled for p in await self.repository.preferences(user_id)}
        out = []
        for category in (dom.Category.SERVICE, dom.Category.COLLECTIONS, dom.Category.MARKETING):
            for channel in dom.Channel:
                default = category != dom.Category.MARKETING
                out.append({"category": category.value, "channel": channel.value,
                            "enabled": stored.get((category.value, channel.value), default)})
        return out

    async def set_preference(self, *, user_id, category, channel, enabled: bool) -> None:
        category, channel = dom.Category(category), dom.Channel(channel)
        if category == dom.Category.TRANSACTIONAL:
            raise dom.NotificationConflict("Transactional messages cannot be switched off")
        await self.repository.set_preference(user_id, category.value, channel.value, enabled)
        await self.session.flush()
        await self.audit.record_customer_action(
            actor_user_id=user_id, action="NOTIFICATION_PREFERENCE_CHANGED", entity_type="notification_preference",
            entity_id=str(user_id), new_value={"category": category.value, "channel": channel.value, "enabled": enabled},
        )

    # ----------------------------------------------------------- admin side

    async def create_template(
        self, *, actor_user_id, template_key, channel, body, allowed_variables, subject=None,
        locale="en", request_id=None, ip_address=None,
    ):
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_MANAGE)
        channel = dom.Channel(channel)
        subject = (subject or "").strip() or None
        category = dom.validate_template(
            key=template_key, body=body, allowed=list(allowed_variables), subject=subject, channel=channel
        )
        admin_id = await self._admin_id(actor_user_id)
        version = await self.repository.next_version(template_key, channel.value, locale)
        row = await self.repository.add_template(
            template_key=template_key, channel=channel.value, locale=locale, version=version,
            category=category.value, subject=subject, body=body,
            allowed_variables=list(allowed_variables), status=dom.TemplateStatus.DRAFT.value,
            created_by_admin_user_id=admin_id,
        )
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="NOTIFICATION_TEMPLATE_CREATED", entity_type=ENTITY_TEMPLATE,
            entity_id=str(row.id), request_id=request_id, ip_address=ip_address,
            new_value={"key": template_key, "channel": channel.value, "version": version},
        )
        return row

    async def decide_template(self, *, actor_user_id, template_id, approve: bool, request_id=None, ip_address=None):
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_APPROVE)
        row = await self.repository.get_template(template_id, for_update=True)
        if row is None:
            raise dom.NotificationNotFound("Template not found")
        if row.status != dom.TemplateStatus.DRAFT.value:
            raise dom.NotificationConflict("Only a draft template can be approved or rejected")
        admin_id = await self._admin_id(actor_user_id)
        if row.created_by_admin_user_id == admin_id:
            raise dom.NotificationConflict("A template cannot be approved by the admin who wrote it")
        row.status = (dom.TemplateStatus.APPROVED if approve else dom.TemplateStatus.REJECTED).value
        row.approved_by_admin_user_id = admin_id
        if approve:
            row.approved_at = utcnow()
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="NOTIFICATION_TEMPLATE_APPROVED" if approve else "NOTIFICATION_TEMPLATE_REJECTED",
            entity_type=ENTITY_TEMPLATE, entity_id=str(row.id), request_id=request_id, ip_address=ip_address,
            new_value={"key": row.template_key, "channel": row.channel, "version": row.version},
        )
        return row

    async def list_templates(self, *, actor_user_id, key=None, status=None, limit=100):
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_READ)
        return await self.repository.list_templates(key=key, status=status, limit=min(limit, 200))

    async def list_notifications(self, *, actor_user_id, status=None, channel=None, template_key=None, user_id=None, limit=100):
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_READ)
        return await self.repository.list(
            user_id=user_id, status=status, channel=channel, template_key=template_key, limit=min(limit, 200)
        )

    async def get_notification(self, *, actor_user_id, notification_id):
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_READ)
        n = await self.repository.get(notification_id)
        if n is None:
            raise dom.NotificationNotFound("Notification not found")
        return n, await self.repository.list_attempts(n.id)

    async def status_counts(self, *, actor_user_id):
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_READ)
        return await self.repository.status_counts()

    async def requeue_dead(self, *, actor_user_id, notification_id, reason, request_id=None, ip_address=None):
        """Give a dead-lettered notification a fresh set of attempts. A person
        decides; the reason is recorded and audited."""
        reason = (reason or "").strip()
        if len(reason) < MIN_REASON:
            raise dom.NotificationError(f"A reason of at least {MIN_REASON} characters is required")
        await self._require(actor_user_id, AdminPermission.NOTIFICATION_MANAGE)
        admin_id = await self._admin_id(actor_user_id)
        n = await self.repository.get(notification_id, for_update=True)
        if n is None:
            raise dom.NotificationNotFound("Notification not found")
        if n.status != dom.Status.DEAD.value:
            raise dom.NotificationConflict("Only a dead-lettered notification can be requeued")
        await self.repository.add_attempt(
            notification_id=n.id, attempt_no=n.attempts, outcome="REQUEUED",
            actor_admin_user_id=admin_id, reason=reason,
        )
        n.status = dom.Status.PENDING.value
        n.attempts = 0
        n.dead_at = None
        n.failure_code = None
        n.next_attempt_at = utcnow()
        await self.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id, action="NOTIFICATION_REQUEUED", entity_type=ENTITY,
            entity_id=str(n.id), request_id=request_id, ip_address=ip_address, reason=reason,
        )
        return n
