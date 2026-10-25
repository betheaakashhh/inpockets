from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LedgerAccount(Base):
    """A chart-of-accounts line. No balance column: balances come from entries."""

    __tablename__ = "ledger_accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ledger_account_code"),
        CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE')",
            name="ck_ledger_account_type",
        ),
        CheckConstraint("normal_side IN ('DEBIT','CREDIT')", name="ck_ledger_account_side"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(12), nullable=False)
    normal_side: Mapped[str] = mapped_column(String(6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LedgerTransaction(Base):
    """Header of one balanced posting. Append-only (database trigger)."""

    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_tx_idempotency_key"),
        UniqueConstraint("reverses_transaction_id", name="uq_ledger_tx_one_reversal"),
        CheckConstraint(
            "kind IN ('DISBURSEMENT','DISBURSEMENT_REVERSAL','REPAYMENT',"
            "'REPAYMENT_REVERSAL','ADJUSTMENT','ADJUSTMENT_REVERSAL')",
            name="ck_ledger_tx_kind",
        ),
        CheckConstraint("entry_count >= 2", name="ck_ledger_tx_entry_count"),
        CheckConstraint("total_amount > 0", name="ck_ledger_tx_total_positive"),
        CheckConstraint(
            "(kind LIKE '%\\_REVERSAL') = (reverses_transaction_id IS NOT NULL)",
            name="ck_ledger_tx_reversal_link",
        ),
        Index("ix_ledger_tx_offer", "loan_offer_id", "posted_at"),
        Index("ix_ledger_tx_source", "source_type", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    loan_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_offers.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reverses_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_transactions.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LedgerEntry(Base):
    """One debit or credit line. Never updated or deleted."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("transaction_id", "line_no", name="uq_ledger_entry_line"),
        CheckConstraint("direction IN ('DEBIT','CREDIT')", name="ck_ledger_entry_direction"),
        CheckConstraint("amount > 0", name="ck_ledger_entry_amount_positive"),
        Index("ix_ledger_entry_account", "account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
