from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class AccountBalanceResponse(BaseModel):
    code: str
    name: str
    account_type: str
    normal_side: str
    debit_total: Decimal
    credit_total: Decimal
    balance: Decimal


class TrialBalanceResponse(BaseModel):
    accounts: list[AccountBalanceResponse]
    total_debits: Decimal
    total_credits: Decimal
    balanced: bool


class LedgerEntryResponse(BaseModel):
    line_no: int
    account_code: str
    direction: str
    amount: Decimal


class LedgerTransactionResponse(BaseModel):
    id: uuid.UUID
    kind: str
    source_type: str
    source_id: uuid.UUID
    loan_offer_id: uuid.UUID
    description: str
    total_amount: Decimal
    entry_count: int
    reverses_transaction_id: uuid.UUID | None
    posted_at: datetime
    entries: list[LedgerEntryResponse] = []

    @classmethod
    def from_row(cls, tx, entries=()) -> LedgerTransactionResponse:
        return cls(
            id=tx.id,
            kind=tx.kind,
            source_type=tx.source_type,
            source_id=tx.source_id,
            loan_offer_id=tx.loan_offer_id,
            description=tx.description,
            total_amount=tx.total_amount,
            entry_count=tx.entry_count,
            reverses_transaction_id=tx.reverses_transaction_id,
            posted_at=tx.posted_at,
            entries=[
                LedgerEntryResponse(
                    line_no=e.line_no, account_code=code, direction=e.direction, amount=e.amount
                )
                for e, code in entries
            ],
        )
