"""Loan pricing math (pure, no I/O).

KreditBee-style structure:
  * interest: annual rate on the sanctioned principal, EMIs on a reducing
    balance (monthly rate = annual / 12);
  * processing fee: percent of principal, deducted from the payout;
  * GST: percent of the fee only;
  * net payout = principal - fee - GST;
  * APR counts the fee and GST (money the customer never receives) and
    excludes penal charges.

All money is Decimal rounded half-up to paise. Nothing here reads settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")
HUNDRED = Decimal(100)
MONTH_DAYS = 30
MAX_MONTHS = 60


class PricingError(ValueError):
    """Invalid pricing configuration or request."""


def q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PricingTerms:
    annual_interest_percent: Decimal
    processing_fee_percent: Decimal
    gst_percent: Decimal

    def validate(self) -> None:
        if not Decimal(0) <= self.annual_interest_percent <= Decimal(100):
            raise PricingError("Interest rate must be between 0 and 100 percent a year")
        if not Decimal(0) <= self.processing_fee_percent <= Decimal(25):
            raise PricingError("Processing fee must be between 0 and 25 percent")
        if not Decimal(0) <= self.gst_percent <= Decimal(50):
            raise PricingError("GST must be between 0 and 50 percent")


@dataclass(frozen=True)
class EmiRow:
    number: int
    due_date: date
    principal: Decimal
    interest: Decimal

    @property
    def total(self) -> Decimal:
        return self.principal + self.interest


@dataclass(frozen=True)
class Quote:
    principal: Decimal
    months: int
    processing_fee: Decimal
    gst: Decimal
    net_payout: Decimal
    emi: Decimal
    total_interest: Decimal
    total_repayable: Decimal
    apr_percent: Decimal


def months_for_tenure(tenure_days: int) -> int:
    """Priced loans are monthly EMIs: the tenure must be whole 30-day months."""
    if tenure_days < MONTH_DAYS or tenure_days % MONTH_DAYS != 0:
        raise PricingError(
            f"Tenure must be a whole number of {MONTH_DAYS}-day months for priced loans"
        )
    months = tenure_days // MONTH_DAYS
    if months > MAX_MONTHS:
        raise PricingError(f"Tenure cannot exceed {MAX_MONTHS} months")
    return months


def fee_and_gst(principal: Decimal, terms: PricingTerms) -> tuple[Decimal, Decimal]:
    fee = q(q(principal) * terms.processing_fee_percent / HUNDRED)
    gst = q(fee * terms.gst_percent / HUNDRED)
    return fee, gst


def emi_schedule(
    *, principal: Decimal, annual_interest_percent: Decimal, months: int, start: date
) -> list[EmiRow]:
    """Equal monthly instalments on a reducing balance.

    Interest each month = balance * annual / 12 (rounded to paise). The EMI is
    fixed (rounded to paise); the LAST row absorbs rounding so principal sums
    exactly to the loan and the balance ends at zero."""
    principal = q(principal)
    if principal <= 0:
        raise PricingError("Principal must be positive")
    if not 1 <= months <= MAX_MONTHS:
        raise PricingError(f"Months must be between 1 and {MAX_MONTHS}")
    rate = Decimal(annual_interest_percent) / HUNDRED / Decimal(12)
    if rate == 0:
        emi = q(principal / months)
    else:
        emi = q(principal * rate / (1 - (1 + rate) ** -months))
    rows: list[EmiRow] = []
    balance = principal
    for n in range(1, months + 1):
        interest = q(balance * rate)
        if n == months:
            part = balance
        else:
            part = emi - interest
            if part <= 0:
                raise PricingError("Instalment too small to cover the interest")
            if part > balance:
                part = balance
        if part <= 0:
            raise PricingError("Schedule collapsed before the last instalment")
        rows.append(
            EmiRow(
                number=n,
                due_date=start + timedelta(days=MONTH_DAYS * n),
                principal=q(part),
                interest=interest,
            )
        )
        balance -= part
    if sum((r.principal for r in rows), Decimal(0)) != principal:
        raise PricingError("Schedule principal does not sum to the loan principal")
    return rows


def apr_percent(*, net_payout: Decimal, payments: list[Decimal]) -> Decimal:
    """Nominal annual rate (monthly IRR x 12) of paying `payments` monthly for
    `net_payout` received today. The payout is net of fee and GST, so those
    are inside the rate. Bisection, 80 iterations, no float."""
    if net_payout <= 0 or not payments:
        raise PricingError("APR needs a positive payout and at least one payment")
    if sum(payments, Decimal(0)) <= net_payout:
        return Decimal("0.00")

    def pv(rate: Decimal) -> Decimal:
        return sum(
            (p / (1 + rate) ** (i + 1) for i, p in enumerate(payments)), Decimal(0)
        ) - net_payout

    lo, hi = Decimal(0), Decimal(10)
    for _ in range(80):
        mid = (lo + hi) / 2
        if pv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return q((lo + hi) / 2 * 12 * HUNDRED)


def quote(*, principal: Decimal, tenure_days: int, terms: PricingTerms, start: date) -> Quote:
    terms.validate()
    principal = q(principal)
    months = months_for_tenure(tenure_days)
    fee, gst = fee_and_gst(principal, terms)
    net = principal - fee - gst
    if net <= 0:
        raise PricingError("Fee and GST would leave nothing to pay out")
    rows = emi_schedule(
        principal=principal,
        annual_interest_percent=terms.annual_interest_percent,
        months=months,
        start=start,
    )
    total_interest = sum((r.interest for r in rows), Decimal(0))
    return Quote(
        principal=principal,
        months=months,
        processing_fee=fee,
        gst=gst,
        net_payout=net,
        emi=rows[0].total,
        total_interest=total_interest,
        total_repayable=principal + total_interest,
        apr_percent=apr_percent(net_payout=net, payments=[r.total for r in rows]),
    )


class PricingNotFound(PricingError):
    pass


class PricingConflict(PricingError):
    pass


# Terms the system writes into an offer's commercial_terms for a priced loan.
# Admins may not supply these (or the older free-form price keys) themselves,
# so what the customer reads in the KFS can never disagree with what is charged.
SYSTEM_TERM_KEYS = frozenset(
    {
        "pricing_version",
        "interest_rate_percent_per_annum",
        "processing_fee_percent",
        "processing_fee_amount",
        "gst_percent_on_processing_fee",
        "gst_amount",
        "net_disbursal_amount",
        "number_of_emis",
        "emi_amount",
        "total_interest",
        "total_repayable",
        "apr_percent_including_fees",
        "late_payment_charges",
    }
)
LEGACY_PRICE_KEYS = frozenset(
    {"interest_rate", "annual_interest_rate", "processing_fee", "gst", "apr"}
)
RESERVED_TERM_KEYS = SYSTEM_TERM_KEYS | LEGACY_PRICE_KEYS


@dataclass(frozen=True)
class LateTerms:
    enabled: bool
    bounce_percent: Decimal
    bounce_cap_amount: Decimal
    penal_annual_percent: Decimal
    penal_max_days: int
    total_cap_percent_of_due: Decimal

    def describe(self) -> str:
        if not self.enabled:
            return "No late or bounce charge is applied."
        return (
            f"Bounce charge: lower of {self.bounce_percent.normalize():f}% of the overdue "
            f"principal or Rs {self.bounce_cap_amount:.2f}; then {self.penal_annual_percent.normalize():f}% "
            f"a year on the overdue principal for up to {self.penal_max_days} days. "
            f"Total late charges are capped at {self.total_cap_percent_of_due.normalize():f}% "
            "of the overdue amount."
        )


def display_terms(*, version: int, terms: PricingTerms, late: LateTerms, qt: Quote) -> dict[str, str]:
    """Plain strings for the KFS / agreement (JSON-safe, no floats)."""

    def pct(v: Decimal) -> str:
        return f"{v.normalize():f}"

    return {
        "pricing_version": str(version),
        "interest_rate_percent_per_annum": pct(terms.annual_interest_percent),
        "processing_fee_percent": pct(terms.processing_fee_percent),
        "processing_fee_amount": f"{qt.processing_fee:.2f}",
        "gst_percent_on_processing_fee": pct(terms.gst_percent),
        "gst_amount": f"{qt.gst:.2f}",
        "net_disbursal_amount": f"{qt.net_payout:.2f}",
        "number_of_emis": str(qt.months),
        "emi_amount": f"{qt.emi:.2f}",
        "total_interest": f"{qt.total_interest:.2f}",
        "total_repayable": f"{qt.total_repayable:.2f}",
        "apr_percent_including_fees": f"{qt.apr_percent:.2f}",
        "late_payment_charges": late.describe(),
    }
