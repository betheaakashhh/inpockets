"""Support & grievance rules (pure, no I/O).

PLACEHOLDER POLICY: the complaint deadline, escalation levels and reopen
window are defaults for review; the lender's grievance-redressal policy owns
the real figures (including who the grievance/nodal officer is).

Who sees what:
  * a customer sees only their own tickets and only customer-visible history
    (never internal notes, assignment or escalation);
  * support staff see every ordinary ticket with internal notes, but only a
    MASKED phone number; the full number is a separate, audited action;
  * tickets about fraud/unauthorised activity or personal data are SENSITIVE:
    only staff with SUPPORT_MANAGE can see or act on them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import StrEnum


class Kind(StrEnum):
    QUESTION = "QUESTION"
    ISSUE = "ISSUE"
    COMPLAINT = "COMPLAINT"  # a grievance: has a resolution deadline and escalation


class Category(StrEnum):
    LOAN_APPLICATION = "LOAN_APPLICATION"
    KYC = "KYC"
    DISBURSEMENT = "DISBURSEMENT"
    REPAYMENT = "REPAYMENT"
    CHARGES = "CHARGES"
    COLLECTIONS_CONDUCT = "COLLECTIONS_CONDUCT"
    FRAUD_OR_UNAUTHORISED = "FRAUD_OR_UNAUTHORISED"
    DATA_PRIVACY = "DATA_PRIVACY"
    OTHER = "OTHER"


SENSITIVE_CATEGORIES = frozenset({Category.FRAUD_OR_UNAUTHORISED, Category.DATA_PRIVACY})


class Priority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Status(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_ON_CUSTOMER = "WAITING_ON_CUSTOMER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.IN_PROGRESS, Status.WAITING_ON_CUSTOMER, Status.RESOLVED}),
    Status.IN_PROGRESS: frozenset({Status.WAITING_ON_CUSTOMER, Status.RESOLVED}),
    Status.WAITING_ON_CUSTOMER: frozenset({Status.IN_PROGRESS, Status.RESOLVED}),
    Status.RESOLVED: frozenset({Status.IN_PROGRESS, Status.CLOSED}),  # IN_PROGRESS = reopened
    Status.CLOSED: frozenset(),
}
LIVE = frozenset({Status.OPEN, Status.IN_PROGRESS, Status.WAITING_ON_CUSTOMER})


class EventType(StrEnum):
    TICKET_CREATED = "TICKET_CREATED"
    CUSTOMER_MESSAGE = "CUSTOMER_MESSAGE"
    AGENT_REPLY = "AGENT_REPLY"
    INTERNAL_NOTE = "INTERNAL_NOTE"
    STATUS_CHANGED = "STATUS_CHANGED"
    ASSIGNED = "ASSIGNED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    ESCALATED = "ESCALATED"
    CONTACT_REVEALED = "CONTACT_REVEALED"


class Visibility(StrEnum):
    CUSTOMER = "CUSTOMER"
    INTERNAL = "INTERNAL"


class ActorType(StrEnum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


# Which events the customer may see.
CUSTOMER_VISIBLE = frozenset(
    {EventType.TICKET_CREATED, EventType.CUSTOMER_MESSAGE, EventType.AGENT_REPLY, EventType.STATUS_CHANGED}
)

MAX_ESCALATION_LEVEL = 2  # 0 support, 1 grievance officer, 2 senior management
REOPEN_WINDOW = timedelta(days=7)
MIN_MESSAGE, MAX_MESSAGE = 1, 2000
MIN_NOTE = 3
MIN_REASON = 10


class SupportError(ValueError):
    pass


class SupportNotFound(SupportError):
    pass


class SupportConflict(SupportError):
    pass


def is_sensitive(category: Category) -> bool:
    return category in SENSITIVE_CATEGORIES


def can_transition(current: Status, new: Status) -> bool:
    return new in TRANSITIONS[current]


def customer_can_reply(status: Status, resolved_at: datetime | None, now: datetime) -> bool:
    """Customers may write on a live ticket, or reopen a resolved one within
    the reopen window. A closed ticket is final: they open a new one."""
    if status in LIVE:
        return True
    if status == Status.RESOLVED:
        return resolved_at is not None and now - resolved_at <= REOPEN_WINDOW
    return False


def sla_due(kind: Kind, created: datetime, days: int) -> datetime | None:
    return created + timedelta(days=days) if kind == Kind.COMPLAINT else None


def is_overdue(status: Status, sla_due_at: datetime | None, now: datetime) -> bool:
    return bool(sla_due_at) and status in LIVE and now > sla_due_at


def mask_phone(phone: str) -> str:
    digits = (phone or "").strip()
    return ("*" * max(len(digits) - 4, 0) + digits[-4:]) if digits else ""


def format_ticket_number(sequence: int, on: date) -> str:
    return f"INP-{on.year}-{sequence:06d}"
