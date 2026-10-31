"""Notification rules (pure, no I/O).

Principles:
  * a message is built only from an APPROVED template version and only from
    the variables that template declares (nothing else can leak into it);
  * what we store is minimal: template key/version and the few variables, never
    the rendered text or the phone number (the destination is looked up at
    send time);
  * transactional messages (money moved, account safety) cannot be switched
    off by a customer; marketing needs an explicit opt-in; everything else is
    on unless the customer turns it off per channel;
  * a message that matters is created at most once (a dedupe key the database
    enforces).

PLACEHOLDER POLICY: retry timings and limits below are defaults for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class Channel(StrEnum):
    SMS = "SMS"
    PUSH = "PUSH"
    EMAIL = "EMAIL"


class Category(StrEnum):
    TRANSACTIONAL = "TRANSACTIONAL"  # money movement, security: always sent
    SERVICE = "SERVICE"  # support, account updates: on unless turned off
    COLLECTIONS = "COLLECTIONS"  # overdue reminders: on unless turned off
    MARKETING = "MARKETING"  # off unless the customer opts in


class Status(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"  # accepted by the provider
    DELIVERED = "DELIVERED"  # provider confirmed delivery
    DELIVERY_FAILED = "DELIVERY_FAILED"  # provider says it did not arrive
    DEAD = "DEAD"  # dead-letter: gave up, a person decides
    SUPPRESSED = "SUPPRESSED"  # deliberately not sent (see reason)


class TemplateStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Suppression(StrEnum):
    USER_NOT_ACTIVE = "USER_NOT_ACTIVE"
    OPTED_OUT = "OPTED_OUT"
    NOT_OPTED_IN = "NOT_OPTED_IN"
    NO_DESTINATION = "NO_DESTINATION"
    NO_APPROVED_TEMPLATE = "NO_APPROVED_TEMPLATE"
    BAD_VARIABLES = "BAD_VARIABLES"


class NotificationError(ValueError):
    pass


class NotificationNotFound(NotificationError):
    pass


class NotificationConflict(NotificationError):
    pass


# template key prefix -> category. A template key must start with one.
PREFIX_CATEGORY = {
    "txn": Category.TRANSACTIONAL,
    "support": Category.SERVICE,
    "collections": Category.COLLECTIONS,
    "marketing": Category.MARKETING,
}
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
VAR_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
MAX_BODY = 1000
MAX_VALUE = 200

MAX_ATTEMPTS = 5
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))
LEASE = timedelta(minutes=10)  # a SENDING row older than this is treated as a crash


def category_for_key(key: str) -> Category:
    if not KEY_RE.match(key or ""):
        raise NotificationError("Template key must look like 'support.ticket_received'")
    prefix = key.split(".", 1)[0]
    if prefix not in PREFIX_CATEGORY:
        raise NotificationError(f"Template key must start with one of {sorted(PREFIX_CATEGORY)}")
    return PREFIX_CATEGORY[prefix]


def placeholders(body: str) -> set[str]:
    return set(VAR_RE.findall(body))


def validate_template(*, key: str, body: str, allowed: list[str], subject: str | None, channel: Channel) -> Category:
    category = category_for_key(key)
    if not body or len(body) > MAX_BODY:
        raise NotificationError(f"Template body must be 1-{MAX_BODY} characters")
    if "{" in VAR_RE.sub("", body) or "}" in VAR_RE.sub("", body):
        raise NotificationError("Template has a malformed {placeholder}")
    if not all(re.fullmatch(r"[a-z][a-z0-9_]*", a) for a in allowed) or len(set(allowed)) != len(allowed):
        raise NotificationError("Allowed variables must be unique lowercase names")
    undeclared = placeholders(body) - set(allowed)
    if undeclared:
        raise NotificationError(f"Template uses undeclared variables: {sorted(undeclared)}")
    if channel == Channel.EMAIL and not (subject or "").strip():
        raise NotificationError("An email template needs a subject")
    if channel != Channel.EMAIL and subject:
        raise NotificationError("Only email templates have a subject")
    return category


def clean_variables(variables: dict, allowed: list[str]) -> dict[str, str]:
    """Only declared variables, as short plain strings. Anything else is refused."""
    if not isinstance(variables, dict):
        raise NotificationError("Variables must be an object")
    extra = set(variables) - set(allowed)
    if extra:
        raise NotificationError(f"Variables not declared by the template: {sorted(extra)}")
    out = {}
    for k, v in variables.items():
        if isinstance(v, bool) or not isinstance(v, (str, int)) and not hasattr(v, "quantize"):
            raise NotificationError(f"Variable {k} must be text or a number")
        text = str(v)
        if len(text) > MAX_VALUE or "\n" in text or "\r" in text:
            raise NotificationError(f"Variable {k} is too long or has line breaks")
        out[k] = text
    return out


def render(body: str, variables: dict[str, str]) -> str:
    missing = placeholders(body) - set(variables)
    if missing:
        raise NotificationError(f"Missing variables: {sorted(missing)}")
    return VAR_RE.sub(lambda m: variables[m.group(1)], body)


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: Suppression | None = None


def eligibility(
    *, category: Category, user_active: bool, has_destination: bool, preference: bool | None
) -> Eligibility:
    """preference: the customer's stored choice for this category and channel
    (None = never chose)."""
    if not user_active:
        return Eligibility(False, Suppression.USER_NOT_ACTIVE)
    if not has_destination:
        return Eligibility(False, Suppression.NO_DESTINATION)
    if category == Category.TRANSACTIONAL:
        return Eligibility(True)  # cannot be switched off
    if category == Category.MARKETING:
        return Eligibility(True) if preference is True else Eligibility(False, Suppression.NOT_OPTED_IN)
    if preference is False:
        return Eligibility(False, Suppression.OPTED_OUT)
    return Eligibility(True)


def backoff_for(attempts_made: int) -> timedelta:
    """Delay before the next try, after `attempts_made` failed attempts."""
    return BACKOFF[min(max(attempts_made, 1), len(BACKOFF)) - 1]
