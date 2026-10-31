from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.notifications import Category, Channel


class TemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str = Field(min_length=3, max_length=80)
    channel: Channel
    locale: str = Field(default="en", min_length=2, max_length=8)
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=1000)
    allowed_variables: list[str] = Field(default_factory=list, max_length=20)


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_key: str
    channel: str
    locale: str
    version: int
    category: str
    subject: str | None
    body: str
    allowed_variables: list[str]
    status: str
    approved_at: datetime | None
    created_at: datetime


class AdminNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    template_key: str
    template_version: int | None
    channel: str
    category: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    provider: str | None
    provider_ref: str | None
    failure_code: str | None
    suppress_reason: str | None
    source_type: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    dead_at: datetime | None
    created_at: datetime


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_no: int
    outcome: str
    failure_code: str | None
    reason: str | None
    created_at: datetime


class AdminNotificationDetail(AdminNotificationResponse):
    attempts_log: list[AttemptResponse]


class StatusCount(BaseModel):
    status: str
    count: int


class RequeueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=10, max_length=1000)


class MyNotificationResponse(BaseModel):
    """What a customer sees: no variables, no provider details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_key: str
    channel: str
    category: str
    status: str
    created_at: datetime
    sent_at: datetime | None


class PreferenceItem(BaseModel):
    category: Category
    channel: Channel
    enabled: bool


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    channel: Channel
    enabled: bool
