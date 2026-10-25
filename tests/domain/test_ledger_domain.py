from decimal import Decimal

import pytest

from app.domain import ledger as L
from app.domain.ledger import Direction, Line, UnbalancedTransaction

D = Decimal


def test_balanced_two_line_transaction_is_accepted():
    lines = [L.debit(L.LOAN_PRINCIPAL, D("100.00")), L.credit(L.BANK, D("100.00"))]
    assert L.validate_lines(lines) == lines
    assert L.total_of(lines) == D("100.00")


def test_multi_line_split_balances():
    lines = [
        L.debit(L.BANK, D("100.00")),
        L.credit(L.LOAN_PRINCIPAL, D("70.00")),
        L.credit(L.INTEREST_INCOME, D("20.00")),
        L.credit(L.FEE_INCOME, D("10.00")),
    ]
    assert len(L.validate_lines(lines)) == 4


@pytest.mark.parametrize(
    "lines",
    [
        [L.debit(L.BANK, D("100.00")), L.credit(L.LOAN_PRINCIPAL, D("99.99"))],
        [L.debit(L.BANK, D("100.00"))],
        [],
        [L.debit(L.BANK, D("100.00")), L.debit(L.LOAN_PRINCIPAL, D("100.00"))],
    ],
)
def test_unbalanced_or_too_short_is_rejected(lines):
    with pytest.raises(UnbalancedTransaction):
        L.validate_lines(lines)


@pytest.mark.parametrize("bad", [D("0"), D("-5.00"), D("1.005"), D("NaN"), D("Infinity")])
def test_amounts_must_be_positive_two_decimal_and_finite(bad):
    with pytest.raises(UnbalancedTransaction):
        L.validate_lines([L.debit(L.BANK, bad), L.credit(L.LOAN_PRINCIPAL, bad)])


def test_mirror_swaps_every_side_and_keeps_amounts():
    lines = [L.debit(L.LOAN_PRINCIPAL, D("5.00")), L.credit(L.BANK, D("5.00"))]
    mirrored = L.mirror(lines)
    assert mirrored == [L.credit(L.LOAN_PRINCIPAL, D("5.00")), L.debit(L.BANK, D("5.00"))]
    # Posting a transaction and its mirror nets every account to zero.
    net: dict[str, Decimal] = {}
    for ln in lines + mirrored:
        sign = 1 if ln.direction == Direction.DEBIT else -1
        net[ln.account_code] = net.get(ln.account_code, D(0)) + sign * ln.amount
    assert set(net.values()) == {D(0)}


def test_payload_hash_ignores_line_order_but_not_content():
    a = [L.debit(L.BANK, D("5.00")), L.credit(L.LOAN_PRINCIPAL, D("5.00"))]
    b = list(reversed(a))
    assert L.payload_hash("REPAYMENT", "o1", a) == L.payload_hash("REPAYMENT", "o1", b)
    changed = [L.debit(L.BANK, D("5.01")), L.credit(L.LOAN_PRINCIPAL, D("5.01"))]
    assert L.payload_hash("REPAYMENT", "o1", a) != L.payload_hash("REPAYMENT", "o1", changed)
    assert L.payload_hash("REPAYMENT", "o1", a) != L.payload_hash("REPAYMENT", "o2", a)
    assert L.payload_hash("REPAYMENT", "o1", a) != L.payload_hash("DISBURSEMENT", "o1", a)


def test_balances_follow_the_natural_side_of_each_account():
    assert L.normal_side("ASSET") == Direction.DEBIT
    assert L.normal_side("EXPENSE") == Direction.DEBIT
    for kind in ("LIABILITY", "EQUITY", "INCOME"):
        assert L.normal_side(kind) == Direction.CREDIT
    assert L.signed_balance("ASSET", D("100"), D("30")) == D("70")
    assert L.signed_balance("LIABILITY", D("30"), D("100")) == D("70")


def test_every_original_kind_has_exactly_one_reversal_kind():
    assert set(L.REVERSAL_OF) == {L.TxKind.DISBURSEMENT, L.TxKind.REPAYMENT, L.TxKind.ADJUSTMENT}
    assert set(L.REVERSAL_OF.values()) == L.REVERSAL_KINDS


def test_system_accounts_cover_every_code_the_services_use():
    for code in (L.BANK, L.LOAN_PRINCIPAL, L.UNAPPLIED_RECEIPTS, L.INTEREST_INCOME, L.FEE_INCOME):
        assert code in L.SYSTEM_ACCOUNTS


def test_line_is_immutable():
    line = Line(L.BANK, Direction.DEBIT, D("1.00"))
    with pytest.raises(Exception):
        line.amount = D("2.00")  # type: ignore[misc]
