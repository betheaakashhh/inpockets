from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.domain import ledger as dom
from app.domain.admin import AdminPermission
from app.domain.ledger import (
    Direction,
    LedgerConflict,
    LedgerNotFound,
    Line,
    TxKind,
)
from app.models.ledger import LedgerTransaction


@dataclass(frozen=True)
class AccountBalance:
    code: str
    name: str
    account_type: str
    normal_side: str
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal


class LedgerService:
    """Posts balanced, append-only transactions and derives balances.

    Callers pass their own session: a posting commits or rolls back together
    with the business change that caused it (disbursement success, payment
    success), so the books and the operational record can never disagree.
    """

    def __init__(self, *, session, repository, admin_authorization_service=None):
        self.session = session
        self.repository = repository
        self.admin_authz = admin_authorization_service

    # ------------------------------------------------------------ posting

    async def post(
        self,
        *,
        kind: TxKind,
        idempotency_key: str,
        source_type: str,
        source_id: uuid.UUID,
        loan_offer_id: uuid.UUID,
        user_id: uuid.UUID,
        lines: list[Line],
        description: str,
        reverses_transaction_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> LedgerTransaction:
        """Idempotent on `idempotency_key`. Replaying a key returns the
        original transaction; replaying it with different content is refused."""
        kind = TxKind(kind)
        clean = dom.validate_lines(lines)
        digest = dom.payload_hash(kind.value, loan_offer_id, clean)

        existing = await self.repository.get_by_key(idempotency_key)
        if existing is not None:
            return self._same_or_conflict(existing, digest)

        accounts = await self.repository.accounts_by_code({ln.account_code for ln in clean})
        for ln in clean:
            account = accounts.get(ln.account_code)
            if account is None:
                raise LedgerNotFound(f"Unknown ledger account {ln.account_code}")
            if not account.is_active:
                raise LedgerConflict(f"Ledger account {ln.account_code} is inactive")

        tx_id = await self.repository.insert_header(
            kind=kind.value,
            idempotency_key=idempotency_key,
            payload_hash=digest,
            source_type=source_type,
            source_id=source_id,
            loan_offer_id=loan_offer_id,
            user_id=user_id,
            currency=dom.CURRENCY,
            description=description[:200],
            entry_count=len(clean),
            total_amount=dom.total_of(clean),
            reverses_transaction_id=reverses_transaction_id,
            reason=reason,
        )
        if tx_id is None:  # lost a race on the key: the winner's row is authoritative
            existing = await self.repository.get_by_key(idempotency_key)
            return self._same_or_conflict(existing, digest)

        await self.repository.insert_entries(
            [
                {
                    "transaction_id": tx_id,
                    "line_no": i,
                    "account_id": accounts[ln.account_code].id,
                    "direction": ln.direction.value,
                    "amount": ln.amount,
                }
                for i, ln in enumerate(clean, start=1)
            ]
        )
        await self.session.flush()
        return await self.repository.get_by_id(tx_id)

    @staticmethod
    def _same_or_conflict(existing: LedgerTransaction, digest: str) -> LedgerTransaction:
        if existing.payload_hash != digest:
            raise LedgerConflict("Idempotency key was already used for a different posting")
        return existing

    async def reverse(
        self,
        *,
        original_transaction_id: uuid.UUID,
        idempotency_key: str,
        source_type: str,
        source_id: uuid.UUID,
        reason: str,
    ) -> LedgerTransaction:
        """Post the exact mirror of an earlier transaction. History is never
        edited: the correction is a new transaction linked to the original,
        and an original can be reversed at most once."""
        original = await self.repository.get_by_id(original_transaction_id, for_update=True)
        if original is None:
            raise LedgerNotFound("Transaction not found")
        kind = TxKind(original.kind)
        if kind not in dom.REVERSAL_OF:
            raise LedgerConflict("A reversal cannot itself be reversed")
        done = await self.repository.get_reversal_of(original.id)
        if done is not None:
            return done  # already reversed: idempotent
        entries = await self.repository.entries_with_accounts(original.id)
        lines = [Line(code, Direction(e.direction), e.amount) for e, code in entries]
        return await self.post(
            kind=dom.REVERSAL_OF[kind],
            idempotency_key=idempotency_key,
            source_type=source_type,
            source_id=source_id,
            loan_offer_id=original.loan_offer_id,
            user_id=original.user_id,
            lines=dom.mirror(lines),
            description=f"Reversal of {original.id}",
            reverses_transaction_id=original.id,
            reason=reason,
        )

    # -------------------------------------------------- business postings

    async def post_disbursement(self, d) -> LedgerTransaction:
        amount = dom.quantize(d.amount)
        return await self.post(
            kind=TxKind.DISBURSEMENT,
            idempotency_key=f"disbursement:{d.id}:paid",
            source_type="disbursement",
            source_id=d.id,
            loan_offer_id=d.loan_offer_id,
            user_id=d.user_id,
            lines=[dom.debit(dom.LOAN_PRINCIPAL, amount), dom.credit(dom.BANK, amount)],
            description=f"Loan disbursed (utr {d.utr or 'n/a'})",
        )

    async def reverse_disbursement(self, d) -> LedgerTransaction | None:
        original = await self.repository.get_by_key(f"disbursement:{d.id}:paid")
        if original is None:
            return None
        return await self.reverse(
            original_transaction_id=original.id,
            idempotency_key=f"disbursement:{d.id}:reversed",
            source_type="disbursement",
            source_id=d.id,
            reason="Provider reported the disbursement reversed",
        )

    async def post_repayment(
        self, *, payment, principal: Decimal, interest: Decimal, fees: Decimal, unapplied: Decimal
    ) -> LedgerTransaction:
        """Cash in. Dr bank for the full amount received; credit the receivable
        for principal, income accounts for interest/fees, and a liability for
        any receipt that matched nothing due (never silently dropped)."""
        total = dom.quantize(payment.amount)
        lines = [dom.debit(dom.BANK, total)]
        for code, amount in (
            (dom.LOAN_PRINCIPAL, principal),
            (dom.INTEREST_INCOME, interest),
            (dom.FEE_INCOME, fees),
            (dom.UNAPPLIED_RECEIPTS, unapplied),
        ):
            if amount > 0:
                lines.append(dom.credit(code, dom.quantize(amount)))
        return await self.post(
            kind=TxKind.REPAYMENT,
            idempotency_key=f"repayment:{payment.id}:received",
            source_type="repayment_payment",
            source_id=payment.id,
            loan_offer_id=payment.loan_offer_id,
            user_id=payment.user_id,
            lines=lines,
            description=f"Repayment received (ref {payment.provider_ref or 'n/a'})",
        )

    async def reverse_repayment(self, payment) -> LedgerTransaction | None:
        original = await self.repository.get_by_key(f"repayment:{payment.id}:received")
        if original is None:
            return None
        return await self.reverse(
            original_transaction_id=original.id,
            idempotency_key=f"repayment:{payment.id}:reversed",
            source_type="repayment_payment",
            source_id=payment.id,
            reason="Provider reported the payment reversed",
        )

    # --------------------------------------------------------------- reads

    async def balances(self, *, loan_offer_id: uuid.UUID | None = None) -> list[AccountBalance]:
        out = []
        for account, debit_total, credit_total in await self.repository.totals_by_account(
            loan_offer_id=loan_offer_id
        ):
            out.append(
                AccountBalance(
                    code=account.code,
                    name=account.name,
                    account_type=account.account_type,
                    normal_side=account.normal_side,
                    debit_total=debit_total,
                    credit_total=credit_total,
                    balance=dom.signed_balance(account.account_type, debit_total, credit_total),
                )
            )
        return out

    async def principal_outstanding(self, loan_offer_id: uuid.UUID) -> Decimal:
        for b in await self.balances(loan_offer_id=loan_offer_id):
            if b.code == dom.LOAN_PRINCIPAL:
                return b.balance
        return Decimal(0)

    async def _require_read(self, actor_user_id):
        await self.admin_authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.LEDGER_READ
        )

    async def admin_trial_balance(self, *, actor_user_id, loan_offer_id=None):
        await self._require_read(actor_user_id)
        rows = await self.balances(loan_offer_id=loan_offer_id)
        return rows, sum((r.debit_total for r in rows), Decimal(0)), sum(
            (r.credit_total for r in rows), Decimal(0)
        )

    async def admin_list_transactions(self, *, actor_user_id, loan_offer_id=None, limit=100):
        await self._require_read(actor_user_id)
        return await self.repository.list_transactions(
            loan_offer_id=loan_offer_id, limit=min(limit, 200)
        )

    async def admin_get_transaction(self, *, actor_user_id, transaction_id):
        await self._require_read(actor_user_id)
        tx = await self.repository.get_by_id(transaction_id)
        if tx is None:
            raise LedgerNotFound("Transaction not found")
        return tx, await self.repository.entries_with_accounts(tx.id)
