"""Reconciliation matching (pure, no I/O).

Compares what WE recorded (customer payments, payouts, and the ledger) with
what the provider/bank says it settled. Rules that never bend:

  * the match key is the provider reference;
  * nothing here changes a payment, a payout or the ledger. A difference is
    reported as a finding for a person to look at, never silently fixed;
  * the same reference appearing twice in a provider report is never counted
    twice: it is flagged for review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

IST = timezone(timedelta(hours=5, minutes=30))
PAISE = Decimal("0.01")


class Flow(StrEnum):
    COLLECTION = "COLLECTION"  # customer repayments coming in
    DISBURSEMENT = "DISBURSEMENT"  # loan payouts going out


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RecordStatus(StrEnum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"  # one side has it, the other does not
    MISMATCH = "MISMATCH"  # both sides have it but disagree
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # duplicate or ledger problem


class Discrepancy(StrEnum):
    MISSING_EXTERNAL = "MISSING_EXTERNAL"  # we say paid, the provider report has nothing
    MISSING_INTERNAL = "MISSING_INTERNAL"  # the provider settled it, we have no record
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    DUPLICATE_EXTERNAL = "DUPLICATE_EXTERNAL"
    LEDGER_MISMATCH = "LEDGER_MISMATCH"  # the books do not agree with the payment


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"


class Resolution(StrEnum):
    EXPLAINED = "EXPLAINED"  # a harmless difference (e.g. settled a day later)
    CORRECTED_ELSEWHERE = "CORRECTED_ELSEWHERE"  # fixed through the normal repayment/ledger flow
    ESCALATED_TO_PROVIDER = "ESCALATED_TO_PROVIDER"  # dispute raised with the provider/bank


class ReconciliationError(ValueError):
    pass


class ReconciliationNotFound(ReconciliationError):
    pass


class ReconciliationConflict(ReconciliationError):
    pass


class ProviderStatus(StrEnum):
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


# What the provider must say for each final internal status.
EXPECTED_EXTERNAL = {
    "SUCCESS": ProviderStatus.SETTLED,
    "REVERSED": ProviderStatus.REVERSED,
    "FAILED": ProviderStatus.FAILED,
}


def q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class InternalItem:
    id: object
    ref: str
    amount: Decimal
    status: str  # our payment/disbursement status
    ledger_net: Decimal  # net movement of the bank account in the ledger for this item


@dataclass(frozen=True)
class ExternalLine:
    line_id: str
    ref: str
    amount: Decimal
    status: str  # SETTLED | FAILED | REVERSED


@dataclass(frozen=True)
class Finding:
    provider_ref: str
    status: RecordStatus
    discrepancy: Discrepancy | None
    internal: InternalItem | None
    external: ExternalLine | None
    external_count: int
    expected_ledger_net: Decimal | None
    detail: str


def day_window(report_date: date) -> tuple[datetime, datetime]:
    """[start, end) of an Indian calendar day, as UTC instants."""
    start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=IST)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def expected_ledger_net(flow: Flow, status: str, amount: Decimal) -> Decimal:
    """How far the bank account should have moved in our books for an item.

    A successful collection puts money IN (+), a successful payout sends it
    OUT (-); a reversed or failed item nets to zero."""
    if status != "SUCCESS":
        return Decimal("0.00")
    return q(amount) if flow == Flow.COLLECTION else -q(amount)


def reconcile(
    *,
    flow: Flow,
    window_items: list[InternalItem],
    lookup: dict[str, InternalItem],
    external: list[ExternalLine],
) -> list[Finding]:
    """One finding per provider reference.

    window_items: our items completed in the report day.
    lookup: our item for every reference the provider reported (any day), so a
            settlement we hold under a different day or status is still found.
    external: every line of the provider's report."""
    groups: dict[str, list[ExternalLine]] = {}
    for line in external:
        groups.setdefault(line.ref, []).append(line)

    findings: list[Finding] = []
    for ref, lines in groups.items():
        item = lookup.get(ref)
        first = lines[0]
        expected = (
            expected_ledger_net(flow, item.status, item.amount) if item is not None else None
        )

        if len(lines) > 1:
            findings.append(
                Finding(
                    ref, RecordStatus.REQUIRES_REVIEW, Discrepancy.DUPLICATE_EXTERNAL,
                    item, first, len(lines), expected,
                    f"The provider report lists this reference {len(lines)} times; "
                    "counted once, needs a person to check.",
                )
            )
            continue

        if item is None:
            findings.append(
                Finding(
                    ref, RecordStatus.UNMATCHED, Discrepancy.MISSING_INTERNAL,
                    None, first, 1, None,
                    "The provider settled this but we have no matching record.",
                )
            )
            continue

        wanted = EXPECTED_EXTERNAL.get(item.status)
        if wanted is None or first.status != wanted:
            findings.append(
                Finding(
                    ref, RecordStatus.MISMATCH, Discrepancy.STATUS_MISMATCH,
                    item, first, 1, expected,
                    f"We have it as {item.status}; the provider says {first.status}.",
                )
            )
            continue

        if q(first.amount) != q(item.amount):
            findings.append(
                Finding(
                    ref, RecordStatus.MISMATCH, Discrepancy.AMOUNT_MISMATCH,
                    item, first, 1, expected,
                    f"We have {q(item.amount)}; the provider says {q(first.amount)}.",
                )
            )
            continue

        if q(item.ledger_net) != expected:
            findings.append(
                Finding(
                    ref, RecordStatus.REQUIRES_REVIEW, Discrepancy.LEDGER_MISMATCH,
                    item, first, 1, expected,
                    f"The books moved the bank account by {q(item.ledger_net)}; "
                    f"expected {expected}.",
                )
            )
            continue

        findings.append(
            Finding(ref, RecordStatus.MATCHED, None, item, first, 1, expected, "Matched.")
        )

    for item in window_items:
        if item.ref in groups:
            continue
        findings.append(
            Finding(
                item.ref, RecordStatus.UNMATCHED, Discrepancy.MISSING_EXTERNAL,
                item, None, 0, expected_ledger_net(flow, item.status, item.amount),
                "We recorded this as settled but the provider report does not list it.",
            )
        )
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    out = {"matched": 0, "unmatched": 0, "mismatch": 0, "requires_review": 0}
    for f in findings:
        out[f.status.value.lower()] += 1
    return out
