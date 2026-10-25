"""Read-only ledger views. There is deliberately no endpoint that edits or
posts entries: history is append-only, and postings come only from verified
business events (disbursement, repayment, their reversals)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.repayment import repayment_http_error
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.models.admin_user import AdminUser
from app.schemas.ledger import (
    AccountBalanceResponse,
    LedgerTransactionResponse,
    TrialBalanceResponse,
)
from app.services.ledger_factory import build_ledger_service

router = APIRouter(dependencies=[Depends(limit_user("admin-ledger"))])


@router.get("/trial-balance", response_model=TrialBalanceResponse)
async def trial_balance(
    loan_offer_id: uuid.UUID | None = None,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_ledger_service(session)
    try:
        rows, debits, credits = await service.admin_trial_balance(
            actor_user_id=admin.user_id, loan_offer_id=loan_offer_id
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return TrialBalanceResponse(
        accounts=[AccountBalanceResponse(**r.__dict__) for r in rows],
        total_debits=debits,
        total_credits=credits,
        balanced=debits == credits,
    )


@router.get("/transactions", response_model=list[LedgerTransactionResponse])
async def list_transactions(
    loan_offer_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_ledger_service(session)
    try:
        rows = await service.admin_list_transactions(
            actor_user_id=admin.user_id, loan_offer_id=loan_offer_id, limit=limit
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return [LedgerTransactionResponse.from_row(t) for t in rows]


@router.get("/transactions/{transaction_id}", response_model=LedgerTransactionResponse)
async def get_transaction(
    transaction_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_ledger_service(session)
    try:
        tx, entries = await service.admin_get_transaction(
            actor_user_id=admin.user_id, transaction_id=transaction_id
        )
    except Exception as exc:
        raise repayment_http_error(exc) from exc
    return LedgerTransactionResponse.from_row(tx, entries)
