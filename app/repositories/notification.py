from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import CollectionCase, CollectionEvent
from app.models.notification import (
    Notification,
    NotificationAttempt,
    NotificationEvent,
    NotificationPreference,
    NotificationTemplate,
)
from app.models.user import User


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------ templates

    async def next_version(self, key: str, channel: str, locale: str) -> int:
        current = (
            await self.session.execute(
                select(func.max(NotificationTemplate.version)).where(
                    NotificationTemplate.template_key == key,
                    NotificationTemplate.channel == channel,
                    NotificationTemplate.locale == locale,
                )
            )
        ).scalar_one()
        return (current or 0) + 1

    async def add_template(self, **fields) -> NotificationTemplate:
        row = NotificationTemplate(id=uuid.uuid4(), **fields)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_template(self, template_id, *, for_update=False):
        stmt = select(NotificationTemplate).where(NotificationTemplate.id == template_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def approved_template(self, key: str, channel: str, locale: str = "en", version: int | None = None):
        stmt = select(NotificationTemplate).where(
            NotificationTemplate.template_key == key,
            NotificationTemplate.channel == channel,
            NotificationTemplate.locale == locale,
            NotificationTemplate.status == "APPROVED",
        )
        if version is not None:
            stmt = stmt.where(NotificationTemplate.version == version)
        stmt = stmt.order_by(NotificationTemplate.version.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_templates(self, *, key=None, status=None, limit=100):
        stmt = select(NotificationTemplate)
        if key:
            stmt = stmt.where(NotificationTemplate.template_key == key)
        if status:
            stmt = stmt.where(NotificationTemplate.status == status)
        rows = await self.session.execute(
            stmt.order_by(NotificationTemplate.template_key, NotificationTemplate.channel,
                          NotificationTemplate.version.desc()).limit(limit)
        )
        return list(rows.scalars())

    # -------------------------------------------------------- notifications

    async def insert(self, **fields) -> uuid.UUID | None:
        """None when the dedupe key already exists."""
        result = await self.session.execute(
            insert(Notification)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(constraint="uq_notification_dedupe_key")
            .returning(Notification.id)
        )
        return result.scalar_one_or_none()

    async def get(self, notification_id, *, for_update=False):
        stmt = select(Notification).where(Notification.id == notification_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_dedupe(self, key: str):
        return (
            await self.session.execute(select(Notification).where(Notification.dedupe_key == key))
        ).scalar_one_or_none()

    async def get_by_provider_ref(self, provider: str, ref: str, *, for_update=False):
        stmt = select(Notification).where(Notification.provider == provider, Notification.provider_ref == ref)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def claim_due(self, *, now: datetime, lease: timedelta, limit: int):
        """Rows ready to send (or stuck SENDING past the lease), locked so
        another worker skips them."""
        rows = await self.session.execute(
            select(Notification)
            .where(
                or_(
                    and_(Notification.status == "PENDING", Notification.next_attempt_at <= now),
                    and_(Notification.status == "SENDING", Notification.locked_at < now - lease),
                )
            )
            .order_by(Notification.next_attempt_at, Notification.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return list(rows.scalars())

    async def list(self, *, user_id=None, status=None, channel=None, template_key=None, limit=100):
        stmt = select(Notification)
        if user_id:
            stmt = stmt.where(Notification.user_id == user_id)
        if status:
            stmt = stmt.where(Notification.status == status)
        if channel:
            stmt = stmt.where(Notification.channel == channel)
        if template_key:
            stmt = stmt.where(Notification.template_key == template_key)
        rows = await self.session.execute(
            stmt.order_by(Notification.created_at.desc(), Notification.id).limit(limit)
        )
        return list(rows.scalars())

    async def status_counts(self):
        rows = await self.session.execute(
            select(Notification.status, func.count()).group_by(Notification.status).order_by(Notification.status)
        )
        return [tuple(r) for r in rows.all()]

    async def add_attempt(self, **fields) -> None:
        await self.session.execute(
            insert(NotificationAttempt).values(id=uuid.uuid4(), **fields).on_conflict_do_nothing()
        )

    async def list_attempts(self, notification_id):
        rows = await self.session.execute(
            select(NotificationAttempt)
            .where(NotificationAttempt.notification_id == notification_id)
            .order_by(NotificationAttempt.created_at, NotificationAttempt.attempt_no)
        )
        return list(rows.scalars())

    # --------------------------------------------------------------- events

    async def insert_event(self, **fields) -> uuid.UUID | None:
        result = await self.session.execute(
            insert(NotificationEvent)
            .values(id=uuid.uuid4(), **fields)
            .on_conflict_do_nothing(constraint="uq_notification_event_provider_event")
            .returning(NotificationEvent.id)
        )
        return result.scalar_one_or_none()

    async def set_event_outcome(self, event_id, outcome: str) -> None:
        row = await self.session.get(NotificationEvent, event_id)
        row.outcome = outcome

    # ---------------------------------------------------------- preferences

    async def preferences(self, user_id):
        rows = await self.session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return list(rows.scalars())

    async def preference(self, user_id, category: str, channel: str) -> bool | None:
        return (
            await self.session.execute(
                select(NotificationPreference.enabled).where(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.category == category,
                    NotificationPreference.channel == channel,
                )
            )
        ).scalar_one_or_none()

    async def set_preference(self, user_id, category: str, channel: str, enabled: bool) -> None:
        stmt = insert(NotificationPreference).values(
            id=uuid.uuid4(), user_id=user_id, category=category, channel=channel, enabled=enabled
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_notification_preference", set_={"enabled": enabled, "updated_at": func.now()}
            )
        )

    async def get_user(self, user_id):
        return (await self.session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    # ----------------------------------------------- collections intake

    async def reminders_without_notification(self, *, limit: int):
        """Collection reminder requests (2.15) not yet turned into a
        notification. The dedupe key ties each request to at most one."""
        key = func.concat("collection_event:", CollectionEvent.id.cast(String))
        rows = await self.session.execute(
            select(CollectionEvent, CollectionCase.user_id)
            .join(CollectionCase, CollectionCase.id == CollectionEvent.case_id)
            .outerjoin(Notification, Notification.dedupe_key == key)
            .where(CollectionEvent.event_type == "REMINDER_SCHEDULED", Notification.id.is_(None))
            .order_by(CollectionEvent.created_at, CollectionEvent.id)
            .limit(limit)
        )
        return list(rows.all())
