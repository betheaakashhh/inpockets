"""Double-entry ledger rules (2.13).

The ledger is the accounting source of truth. Balances are *derived* from
entries on read and are never stored or edited anywhere, so no screen, cache
or status field can drift from the books.

Scope (deliberately narrow until commercial/accounting rules are approved):
  * DISBURSEMENT           Dr loan principal receivable   / Cr bank
  * REPAYMENT              Dr bank / Cr loan principal receivable
                           (+ interest/fee income, only when explicitly
                            enabled by approved accounting rules)
  * *_REVERSAL             exact mirror of the original transaction
  * ADJUSTMENT             reserved; no endpoint posts it yet
Refund and write-off are NOT modelled yet: they must be designed with
accounting sign-off before any code may post them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

PAISE = Decimal("0.01")
CURRENCY = "INR"


class AccountType(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class Direction(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


DEBIT_NORMAL = frozenset({AccountType.ASSET, AccountType.EXPENSE})


def normal_side(account_type: str) -> Direction:
    return Direction.DEBIT if AccountType(account_type) in DEBIT_NORMAL else Direction.CREDIT


class TxKind(StrEnum):
    DISBURSEMENT = "DISBURSEMENT"
    DISBURSEMENT_REVERSAL = "DISBURSEMENT_REVERSAL"
    REPAYMENT = "REPAYMENT"
    REPAYMENT_REVERSAL = "REPAYMENT_REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"
    ADJUSTMENT_REVERSAL = "ADJUSTMENT_REVERSAL"


REVERSAL_OF = {
    TxKind.DISBURSEMENT: TxKind.DISBURSEMENT_REVERSAL,
    TxKind.REPAYMENT: TxKind.REPAYMENT_REVERSAL,
    TxKind.ADJUSTMENT: TxKind.ADJUSTMENT_REVERSAL,
}
REVERSAL_KINDS = frozenset(REVERSAL_OF.values())

# System accounts (seeded by migration). Codes are stable identifiers.
BANK = "BANK_CLEARING"
LOAN_PRINCIPAL = "LOAN_PRINCIPAL_RECEIVABLE"
UNAPPLIED_RECEIPTS = "UNAPPLIED_RECEIPTS"
INTEREST_INCOME = "INTEREST_INCOME"
FEE_INCOME = "FEE_INCOME"

SYSTEM_ACCOUNTS: dict[str, tuple[str, AccountType]] = {
    BANK: ("Bank / settlement clearing", AccountType.ASSET),
    LOAN_PRINCIPAL: ("Loan principal receivable", AccountType.ASSET),
    UNAPPLIED_RECEIPTS: ("Customer receipts not yet applied", AccountType.LIABILITY),
    INTEREST_INCOME: ("Interest income", AccountType.INCOME),
    FEE_INCOME: ("Fee income", AccountType.INCOME),
}


@dataclass(frozen=True)
class Line:
    account_code: str
    direction: Direction
    amount: Decimal


def debit(account_code: str, amount: Decimal) -> Line:
    return Line(account_code, Direction.DEBIT, amount)


def credit(account_code: str, amount: Decimal) -> Line:
    return Line(account_code, Direction.CREDIT, amount)


def quantize(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(PAISE, rounding=ROUND_HALF_EVEN)


class LedgerError(ValueError):
    pass


class LedgerNotFound(LedgerError):
    pass


class LedgerConflict(LedgerError):
    pass


class UnbalancedTransaction(LedgerError):
    pass


def validate_lines(lines: list[Line]) -> list[Line]:
    """Pure rule check. Returns normalised lines or raises."""
    if len(lines) < 2:
        raise UnbalancedTransaction("A transaction needs at least two entries")
    clean: list[Line] = []
    for ln in lines:
        amount = Decimal(ln.amount)
        if not amount.is_finite() or amount <= 0:
            raise UnbalancedTransaction("Entry amounts must be positive")
        if amount != quantize(amount):
            raise UnbalancedTransaction("Entry amounts are limited to two decimals")
        clean.append(Line(ln.account_code, Direction(ln.direction), amount))
    debits = sum((ln.amount for ln in clean if ln.direction == Direction.DEBIT), Decimal(0))
    credits = sum((ln.amount for ln in clean if ln.direction == Direction.CREDIT), Decimal(0))
    if debits != credits:
        raise UnbalancedTransaction(f"Debits {debits} do not equal credits {credits}")
    return clean


def total_of(lines: list[Line]) -> Decimal:
    return sum((ln.amount for ln in lines if ln.direction == Direction.DEBIT), Decimal(0))


def payload_hash(kind: str, loan_offer_id, lines: list[Line]) -> str:
    """Stable fingerprint: replaying a key with different content is refused."""
    body = "|".join(
        [str(kind), str(loan_offer_id)]
        + sorted(f"{ln.account_code}:{ln.direction.value}:{ln.amount}" for ln in lines)
    )
    return hashlib.sha256(body.encode()).hexdigest()


def mirror(lines: list[Line]) -> list[Line]:
    return [
        Line(
            ln.account_code,
            Direction.CREDIT if ln.direction == Direction.DEBIT else Direction.DEBIT,
            ln.amount,
        )
        for ln in lines
    ]


def signed_balance(account_type: str, debit_total: Decimal, credit_total: Decimal) -> Decimal:
    """Balance in the account's natural direction (positive = normal)."""
    if normal_side(account_type) == Direction.DEBIT:
        return debit_total - credit_total
    return credit_total - debit_total


def utcnow() -> datetime:
    return datetime.now(UTC)
