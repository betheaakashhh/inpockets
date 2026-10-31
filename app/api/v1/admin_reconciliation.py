"""Admin reconciliation: runs, findings and the review workflow.

There is deliberately no endpoint that edits a payment, a payout or a ledger
entry, and none that edits a finding's numbers. Reviewing only records how a
difference was handled; corrections use the normal repayment/ledger flows."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.loan_offer_errors import client_ip
from app.core.admin import get_current_admin
from app.core.rate_limit import limit_user
from app.db.session import get_db_session
from app.domain import reconciliation as dom
from app.models.admin_user import AdminUser
from app.schemas.reconciliation import (
    OpenSummaryResponse,
    OpenSummaryRow,
    RecordResponse,
    ResolveRequest,
    RunResponse,
    RunStartRequest,
    RunStartResponse,
)
from app.services.reconciliation_factory import build_reconciliation_service
from app.services.reconciliation_runner import run_reconciliation

router = APIRouter(dependencies=[Depends(limit_user("admin-reconciliation"))])
WRITE = [Depends(limit_user("admin-reconciliation-write", sensitive=True))]


def recon_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, dom.ReconciliationNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")
    if isinstance(exc, dom.ReconciliationConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    raise exc


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/runs", response_model=RunStartResponse, dependencies=WRITE)
async def start_run(
    payload: RunStartRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Reconcile one flow for one past day now (the worker does this on a
    schedule). A completed day is never redone; a failed or crashed one is retried."""
    try:
        outcome = await run_reconciliation(
            payload.flow,
            payload.report_date,
            actor_user_id=admin.user_id,
            request_id=_rid(request),
            ip_address=client_ip(request),
        )
        run = None
        if outcome.claim.run_id is not None:
            run = await build_reconciliation_service(session).get_run(
                actor_user_id=admin.user_id, run_id=outcome.claim.run_id
            )
    except Exception as exc:
        raise recon_http_error(exc) from exc
    if outcome.status == "SKIPPED":
        reason = outcome.claim.reason
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That day is already reconciled"
            if reason == "already_completed"
            else "That day is being reconciled right now",
        )
    return RunStartResponse(
        outcome=outcome.status, reason=outcome.claim.reason,
        run=RunResponse.model_validate(run) if run else None,
    )


@router.get("/runs", response_model=list[RunResponse])
async def list_runs(
    flow: dom.Flow | None = None,
    run_status: dom.RunStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_reconciliation_service(session).list_runs(
            actor_user_id=admin.user_id,
            flow=flow.value if flow else None,
            status=run_status.value if run_status else None,
            limit=limit,
        )
    except Exception as exc:
        raise recon_http_error(exc) from exc
    return [RunResponse.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row = await build_reconciliation_service(session).get_run(
            actor_user_id=admin.user_id, run_id=run_id
        )
    except Exception as exc:
        raise recon_http_error(exc) from exc
    return RunResponse.model_validate(row)


@router.get("/summary", response_model=OpenSummaryResponse)
async def open_summary(
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """What still needs a person: open findings by flow and kind."""
    try:
        rows = await build_reconciliation_service(session).open_summary(actor_user_id=admin.user_id)
    except Exception as exc:
        raise recon_http_error(exc) from exc
    return OpenSummaryResponse(
        total_open=sum(r[3] for r in rows),
        rows=[OpenSummaryRow(flow=r[0], status=r[1], review_status=r[2], count=r[3]) for r in rows],
    )


@router.get("/records", response_model=list[RecordResponse])
async def list_records(
    run_id: uuid.UUID | None = None,
    flow: dom.Flow | None = None,
    record_status: dom.RecordStatus | None = Query(default=None, alias="status"),
    review_status: dom.ReviewStatus | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await build_reconciliation_service(session).list_records(
            actor_user_id=admin.user_id,
            run_id=run_id,
            flow=flow.value if flow else None,
            status=record_status.value if record_status else None,
            review_status=review_status.value if review_status else None,
            limit=limit,
        )
    except Exception as exc:
        raise recon_http_error(exc) from exc
    return [RecordResponse.model_validate(r) for r in rows]


@router.get("/records/{record_id}", response_model=RecordResponse)
async def get_record(
    record_id: uuid.UUID,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row = await build_reconciliation_service(session).get_record(
            actor_user_id=admin.user_id, record_id=record_id
        )
    except Exception as exc:
        raise recon_http_error(exc) from exc
    return RecordResponse.model_validate(row)


@router.post("/records/{record_id}/start-review", response_model=RecordResponse, dependencies=WRITE)
async def start_review(
    record_id: uuid.UUID,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_reconciliation_service(session)
    try:
        row = await service.start_review(
            actor_user_id=admin.user_id, record_id=record_id,
            request_id=_rid(request), ip_address=client_ip(request),
        )
        await session.commit()
        return RecordResponse.model_validate(row)
    except Exception as exc:
        await session.rollback()
        raise recon_http_error(exc) from exc


@router.post("/records/{record_id}/resolve", response_model=RecordResponse, dependencies=WRITE)
async def resolve_record(
    record_id: uuid.UUID,
    payload: ResolveRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = build_reconciliation_service(session)
    try:
        row = await service.resolve(
            actor_user_id=admin.user_id, record_id=record_id,
            resolution=payload.resolution, note=payload.note,
            request_id=_rid(request), ip_address=client_ip(request),
        )
        await session.commit()
        return RecordResponse.model_validate(row)
    except Exception as exc:
        await session.rollback()
        raise recon_http_error(exc) from exc
