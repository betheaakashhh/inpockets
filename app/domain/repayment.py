"""Repayment rules (2.12).

POLICY (defined before implementation, as the plan requires; the lender
should confirm these before go-live):

Allocation order
  Oldest installment first (by installment number). Inside an installment:
  fees, then interest, then principal.

Partial payment
  Allowed (any amount > 0 up to the total outstanding). It is applied by the
  order above. An installment that is partly covered is PARTIALLY_PAID and
  keeps its remaining amount due.

Early payment
  Allowed. It is applied to the oldest unpaid installments, including ones
  not yet due. There is NO interest rebate or recalculation: no commercial
  rule for that is approved, so the schedule is never rewritten.

Late payment
  An installment past its due date and not fully paid is OVERDUE. This is
  derived on read, never stored. NO late fee or penal interest is generated:
  there is no approved rule. When one is approved it must arrive as an
  explicit, ledgered fee, not as a silent change to a schedule.

Over-collection
  A payment is capped at the outstanding total when it is requested. If two
  in-flight payments race and money arrives beyond what is due, the excess is
  recorded as unapplied (a liability in the ledger) and flagged, never lost
  and never spread onto installments that do not exist.

Reversal
  A reversed payment undoes exactly the allocations it made (stored per
  payment) and posts the mirror ledger transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

PAISE = Decimal("0.01")
IST = timedelta(hours=5, minutes=30)


class PaymentStatus(StrEnum):
    INITIATED = "INITIATED"  # recorded, provider not yet confirmed to hold it
    PENDING = "PENDING"  # provider holds it; awaiting the customer/bank
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REVERSED = "REVERSED"  # paid, then returned
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


P = PaymentStatus

TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    P.INITIATED: frozenset({P.PENDING, P.SUCCESS, P.FAILED, P.REQUIRES_REVIEW}),
    P.PENDING: frozenset({P.SUCCESS, P.FAILED, P.REQUIRES_REVIEW}),
    P.SUCCESS: frozenset({P.REVERSED}),
    # A success after a failure means money may have moved: a human looks.
    P.FAILED: frozenset({P.REQUIRES_REVIEW}),
    P.REQUIRES_REVIEW: frozenset({P.SUCCESS, P.FAILED}),
    P.REVERSED: frozenset(),
}

OPEN_STATUSES = frozenset({P.INITIATED, P.PENDING, P.REQUIRES_REVIEW})
MAX_OPEN_PAYMENTS_PER_SCHEDULE = 5

PROVIDER_STATUSES = frozenset({"PENDING", "SUCCESS", "FAILED", "REVERSED"})

CUSTOMER_STATUS = {
    P.INITIATED: "PROCESSING",
    P.PENDING: "PROCESSING",
    P.REQUIRES_REVIEW: "PROCESSING",
    P.SUCCESS: "PAID",
    P.FAILED: "FAILED",
    P.REVERSED: "REVERSED",
}

FAILURE_CODES = frozenset(
    {"PROVIDER_REJECTED", "INSUFFICIENT_FUNDS", "BANK_DECLINED", "EXPIRED", "CANCELLED",
     "PROVIDER_FAILED", "PROVIDER_NOT_FOUND"}
)


class ScheduleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class InstallmentStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


MAX_INSTALLMENTS = 60
MAX_INTERVAL_DAYS = 365


class RepaymentError(ValueError):
    pass


class RepaymentNotFound(RepaymentError):
    pass


class RepaymentConflict(RepaymentError):
    pass


class RepaymentUnavailable(RepaymentError):
    """Provider unreachable and the outcome is unknown."""


def utcnow() -> datetime:
    """Single clock for this module (tests fast-forward it)."""
    return datetime.now(UTC)


def today_ist(now: datetime | None = None) -> date:
    return ((now or utcnow()) + IST).date()


def can_transition(current: PaymentStatus, new: PaymentStatus) -> bool:
    return new in TRANSITIONS[current]


def q(amount) -> Decimal:
    return Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_EVEN)


# --------------------------------------------------------------- schedule


@dataclass(frozen=True)
class InstallmentPlan:
    number: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    fee_due: Decimal


def build_schedule(
    *,
    principal: Decimal,
    count: int,
    start: date,
    interval_days: int,
    annual_rate_percent: Decimal | None = None,
) -> list[InstallmentPlan]:
    """Equal-principal installments split in whole paise (the leftover paise go
    to the last installments) so principal always sums exactly. Interest (only when the offer
    states a rate) is simple interest on the principal still outstanding,
    actual/365. Fees are never generated here."""
    principal = q(principal)
    if principal <= 0:
        raise RepaymentError("Principal must be positive")
    if not 1 <= count <= MAX_INSTALLMENTS:
        raise RepaymentError(f"Installment count must be between 1 and {MAX_INSTALLMENTS}")
    if not 1 <= interval_days <= MAX_INTERVAL_DAYS:
        raise RepaymentError(f"Interval must be between 1 and {MAX_INTERVAL_DAYS} days")
    # Split in whole paise so the parts always sum exactly; the leftover
    # paise go one each to the LAST installments (never a negative remainder).
    total_paise = int((principal * 100).to_integral_value())
    base_paise, extra = divmod(total_paise, count)
    if base_paise < 1:
        raise RepaymentError("Principal is too small for that many installments")
    plans: list[InstallmentPlan] = []
    remaining = principal
    for n in range(1, count + 1):
        paise = base_paise + (1 if n > count - extra else 0)
        part = Decimal(paise) / 100
        interest = Decimal("0.00")
        if annual_rate_percent:
            interest = q(remaining * annual_rate_percent / Decimal(100) * interval_days / Decimal(365))
        plans.append(
            InstallmentPlan(
                number=n,
                due_date=start + timedelta(days=interval_days * n),
                principal_due=part,
                interest_due=interest,
                fee_due=Decimal("0.00"),
            )
        )
        remaining -= part
    if sum((p.principal_due for p in plans), Decimal(0)) != principal:
        raise RepaymentError("Schedule principal does not sum to the loan principal")
    return plans


# ------------------------------------------------------------- allocation


@dataclass
class InstallmentState:
    id: object
    number: int
    due_date: date
    principal_due: Decimal
    interest_due: Decimal
    fee_due: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    fee_paid: Decimal

    @property
    def outstanding(self) -> Decimal:
        return (
            (self.principal_due - self.principal_paid)
            + (self.interest_due - self.interest_paid)
            + (self.fee_due - self.fee_paid)
        )


@dataclass(frozen=True)
class Allocation:
    installment_id: object
    fee: Decimal
    interest: Decimal
    principal: Decimal

    @property
    def total(self) -> Decimal:
        return self.fee + self.interest + self.principal


def allocate(
    installments: list[InstallmentState], amount: Decimal
) -> tuple[list[Allocation], Decimal]:
    """Apply `amount` oldest-first, fees -> interest -> principal. Pure.

    Returns (allocations, unapplied remainder)."""
    remaining = q(amount)
    out: list[Allocation] = []
    for inst in sorted(installments, key=lambda i: i.number):
        if remaining <= 0:
            break
        fee = min(remaining, inst.fee_due - inst.fee_paid)
        remaining -= fee
        interest = min(remaining, inst.interest_due - inst.interest_paid)
        remaining -= interest
        principal = min(remaining, inst.principal_due - inst.principal_paid)
        remaining -= principal
        if fee + interest + principal > 0:
            out.append(Allocation(inst.id, fee, interest, principal))
    return out, remaining


def stored_status(inst: InstallmentState) -> InstallmentStatus:
    if inst.outstanding == 0:
        return InstallmentStatus.PAID
    if inst.principal_paid + inst.interest_paid + inst.fee_paid == 0:
        return InstallmentStatus.SCHEDULED
    return InstallmentStatus.PARTIALLY_PAID


def effective_status(status: str, due_date: date, today: date) -> str:
    """Customer-facing: unpaid and past due reads OVERDUE (derived)."""
    if status != InstallmentStatus.PAID.value and due_date < today:
        return "OVERDUE"
    return status
