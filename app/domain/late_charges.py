"""Late / bounce charges, KreditBee format (pure, no I/O).

For one overdue installment, counting the day after its due date as day 1:
  * day 1                  bounce charge = lower of `bounce_percent` of the
                           overdue principal or the fixed cap (Rs 500);
  * days 2..penal_max_days one day of penal charge = overdue principal x
                           penal annual rate / 365;
  * nothing after that, and never more in total than `total_cap` percent of
    what the installment was due (principal + interest).
The basis is the principal still unpaid that day (penal charges are charged
on overdue principal only, never on interest or on earlier charges, so they
can never compound). Charges stop on their own once the principal is paid.
GST on these charges is NOT applied: whether it is due is an open tax
question for the lender's advisers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.domain.pricing import HUNDRED, LateTerms, q

BOUNCE = "BOUNCE"
PENAL = "PENAL"
KINDS = (BOUNCE, PENAL)


@dataclass(frozen=True)
class Charge:
    kind: str
    charge_date: date
    basis: Decimal
    amount: Decimal


def day_number(due_date: date, on: date) -> int:
    """Day 1 is the first day after the due date; 0 or less means not overdue."""
    return (on - due_date).days


def bounce_amount(overdue_principal: Decimal, terms: LateTerms) -> Decimal:
    return q(min(q(overdue_principal * terms.bounce_percent / HUNDRED), terms.bounce_cap_amount))


def penal_amount(overdue_principal: Decimal, terms: LateTerms) -> Decimal:
    return q(overdue_principal * terms.penal_annual_percent / HUNDRED / Decimal(365))


def total_cap(principal_due: Decimal, interest_due: Decimal, terms: LateTerms) -> Decimal:
    return q((principal_due + interest_due) * terms.total_cap_percent_of_due / HUNDRED)


def charge_for_day(
    *,
    due_date: date,
    on: date,
    overdue_principal: Decimal,
    already_charged: Decimal,
    principal_due: Decimal,
    interest_due: Decimal,
    terms: LateTerms,
) -> Charge | None:
    """The single charge (if any) the installment incurs on day `on`."""
    if not terms.enabled or overdue_principal <= 0:
        return None
    n = day_number(due_date, on)
    if n < 1 or n > terms.penal_max_days:
        return None
    if n == 1:
        kind, amount = BOUNCE, bounce_amount(overdue_principal, terms)
    else:
        kind, amount = PENAL, penal_amount(overdue_principal, terms)
    room = total_cap(principal_due, interest_due, terms) - already_charged
    amount = min(amount, room)
    if amount <= 0:
        return None
    return Charge(kind=kind, charge_date=on, basis=q(overdue_principal), amount=q(amount))


def days_to_assess(due_date: date, last_assessed: date | None, today: date, terms: LateTerms) -> list[date]:
    """Days still to be charged, oldest first, never beyond today or the last
    penal day. If the job missed days they are assessed on the basis known
    now, which can only be equal to or lower than what was owed then."""
    first = due_date + timedelta(days=1)
    start = first if last_assessed is None else last_assessed + timedelta(days=1)
    end = min(today, due_date + timedelta(days=terms.penal_max_days))
    out: list[date] = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out
