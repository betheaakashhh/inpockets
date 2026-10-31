"""Collections rules (pure, no I/O).

PLACEHOLDER POLICY: the reminder milestones and escalation thresholds below
are sensible defaults for review. The lender's collections policy and approved
customer wording own the real values; nothing is sent to a customer here (this
module only decides WHEN a reminder or escalation is due).

Days past due (DPD) = today - due date of the oldest installment whose
principal or interest is still unpaid. On the due date itself DPD is 0 (not
overdue); the day after it is 1. Late charges alone never make a loan overdue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

MONEY0 = Decimal("0.00")


class CaseStatus(StrEnum):
    OPEN = "OPEN"  # overdue, not yet worked
    IN_PROGRESS = "IN_PROGRESS"  # an agent has acted on it
    ESCALATED = "ESCALATED"  # raised above the first line
    CLOSED = "CLOSED"


class CloseReason(StrEnum):
    CURED = "CURED"  # nothing overdue any more
    LOAN_INACTIVE = "LOAN_INACTIVE"  # the repayment schedule is no longer active


class EventType(StrEnum):
    CASE_OPENED = "CASE_OPENED"
    BUCKET_CHANGED = "BUCKET_CHANGED"
    ASSIGNED = "ASSIGNED"
    NOTE_ADDED = "NOTE_ADDED"
    CONTACT_ATTEMPT = "CONTACT_ATTEMPT"
    NEXT_ACTION_SET = "NEXT_ACTION_SET"
    REMINDER_SCHEDULED = "REMINDER_SCHEDULED"
    ESCALATED = "ESCALATED"
    CASE_CLOSED = "CASE_CLOSED"


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"
    ADMIN = "ADMIN"


class Channel(StrEnum):
    SMS = "SMS"
    PUSH = "PUSH"
    EMAIL = "EMAIL"
    CALL = "CALL"
    WHATSAPP = "WHATSAPP"


# Channels a reminder may be scheduled on (CALL is a human action, not a reminder).
REMINDER_CHANNELS = frozenset({Channel.SMS, Channel.PUSH, Channel.EMAIL})


class ContactOutcome(StrEnum):
    NO_ANSWER = "NO_ANSWER"
    CONTACTED = "CONTACTED"
    WRONG_NUMBER = "WRONG_NUMBER"
    REFUSED = "REFUSED"
    CALL_BACK_REQUESTED = "CALL_BACK_REQUESTED"


class NextAction(StrEnum):
    CALL = "CALL"
    SEND_REMINDER = "SEND_REMINDER"
    FOLLOW_UP = "FOLLOW_UP"
    ESCALATION_REVIEW = "ESCALATION_REVIEW"


class CollectionsError(ValueError):
    pass


class CollectionsNotFound(CollectionsError):
    pass


class CollectionsConflict(CollectionsError):
    pass


# (lowest DPD, bucket label); the last bucket is open-ended.
BUCKETS: tuple[tuple[int, str], ...] = (
    (1, "1-7"),
    (8, "8-30"),
    (31, "31-60"),
    (61, "61-90"),
    (91, "91+"),
)
BUCKET_LABELS = tuple(label for _, label in BUCKETS)

# DPD milestone -> channels a reminder is scheduled on. Placeholder values.
REMINDER_MILESTONES: dict[int, tuple[Channel, ...]] = {
    1: (Channel.SMS, Channel.PUSH),
    3: (Channel.SMS,),
    7: (Channel.SMS, Channel.PUSH),
    15: (Channel.SMS,),
    30: (Channel.SMS, Channel.EMAIL),
}

# Escalation level -> lowest DPD that raises it. Placeholder values.
ESCALATION_THRESHOLDS: dict[int, int] = {1: 30, 2: 60, 3: 90}
MAX_LEVEL = max(ESCALATION_THRESHOLDS)


def bucket_for(dpd: int) -> str | None:
    """None when not overdue."""
    if dpd < 1:
        return None
    label = None
    for low, name in BUCKETS:
        if dpd >= low:
            label = name
    return label


def bucket_range(label: str) -> tuple[int, int | None]:
    for i, (low, name) in enumerate(BUCKETS):
        if name == label:
            high = BUCKETS[i + 1][0] - 1 if i + 1 < len(BUCKETS) else None
            return low, high
    raise CollectionsError(f"Unknown bucket {label}")


@dataclass(frozen=True)
class InstallmentView:
    id: object
    number: int
    due_date: date
    principal_outstanding: Decimal
    interest_outstanding: Decimal
    fee_outstanding: Decimal


@dataclass(frozen=True)
class Overdue:
    oldest_installment_id: object
    oldest_due_date: date
    dpd: int
    principal: Decimal
    interest: Decimal
    fees: Decimal

    @property
    def total(self) -> Decimal:
        return self.principal + self.interest + self.fees


def overdue_of(installments: list[InstallmentView], today: date) -> Overdue | None:
    """None when no installment is past due with principal or interest unpaid."""
    late = [
        i
        for i in installments
        if i.due_date < today and (i.principal_outstanding + i.interest_outstanding) > 0
    ]
    if not late:
        return None
    oldest = min(late, key=lambda i: (i.due_date, i.number))
    return Overdue(
        oldest_installment_id=oldest.id,
        oldest_due_date=oldest.due_date,
        dpd=(today - oldest.due_date).days,
        principal=sum((i.principal_outstanding for i in late), MONEY0),
        interest=sum((i.interest_outstanding for i in late), MONEY0),
        fees=sum((i.fee_outstanding for i in late), MONEY0),
    )


def due_reminder_milestone(dpd: int) -> int | None:
    """The one milestone to remind for now: the highest already reached.

    After downtime we send the latest reminder only, never a burst of every
    missed one."""
    reached = [m for m in REMINDER_MILESTONES if m <= dpd]
    return max(reached) if reached else None


def reminder_key(installment_id, milestone: int, channel: Channel) -> str:
    return f"reminder:{installment_id}:{milestone}:{channel.value}"


def escalation_level_for(dpd: int) -> int:
    level = 0
    for lvl, threshold in ESCALATION_THRESHOLDS.items():
        if dpd >= threshold:
            level = max(level, lvl)
    return level


def escalation_key(installment_id, level: int) -> str:
    return f"escalate:{installment_id}:{level}"
