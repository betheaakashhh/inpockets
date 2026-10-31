from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import CollectionCase
from app.models.credit_assessment import CreditAssessment
from app.models.disbursement import Disbursement
from app.models.fraud_assessment import FraudAssessment
from app.models.loan_application import LoanApplication
from app.models.loan_decision import LoanDecision
from app.models.notification import Notification
from app.models.reconciliation import ReconciliationRecord
from app.models.repayment import RepaymentInstallment, RepaymentPayment, RepaymentSchedule
from app.models.risk_assessment import RiskAssessment


class ReportingRepository:
    """Read-only reporting queries over the authoritative transactional tables."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _grouped(
        self,
        model,
        group_column,
        *,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        query: Select = select(
            group_column.label("group"),
            func.count(model.id).label("count"),
        )
        created = getattr(model, "created_at", None)
        if created is not None and start_at:
            query = query.where(created >= start_at)
        if created is not None and end_at:
            query = query.where(created < end_at)
        result = await self.session.execute(
            query.group_by(group_column).order_by(func.count(model.id).desc())
            .offset(offset).limit(limit + 1)
        )
        return [{"group": row.group, "count": row.count} for row in result]

    async def applications(self, **filters) -> list[dict]:
        return await self._grouped(
            LoanApplication, LoanApplication.status, **filters
        )

    async def decisions(self, **filters) -> list[dict]:
        query = select(
            LoanDecision.decision_route.label("route"),
            LoanApplication.status.label("application_status"),
            func.count(LoanDecision.id).label("count"),
        ).join(
            LoanApplication, LoanApplication.id == LoanDecision.loan_application_id
        )
        query = self._date_filter(query, LoanDecision.created_at, filters)
        result = await self.session.execute(
            query.group_by(LoanDecision.decision_route, LoanApplication.status)
            .order_by(func.count(LoanDecision.id).desc())
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {
                "route": row.route,
                "application_status": row.application_status,
                "count": row.count,
            }
            for row in result
        ]

    async def disbursements(self, **filters) -> list[dict]:
        query = select(
            Disbursement.status.label("status"),
            func.count(Disbursement.id).label("count"),
            func.coalesce(func.sum(Disbursement.amount), 0).label("amount"),
        )
        query = self._date_filter(query, Disbursement.created_at, filters)
        result = await self.session.execute(
            query.group_by(Disbursement.status).order_by(Disbursement.status)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {"status": row.status, "count": row.count, "amount": str(row.amount)}
            for row in result
        ]

    async def exposure(self, **filters) -> list[dict]:
        query = select(
            func.coalesce(func.sum(RepaymentInstallment.principal_due), 0).label("principal_due"),
            func.coalesce(func.sum(RepaymentInstallment.principal_paid), 0).label("principal_paid"),
            func.count(RepaymentInstallment.id).label("installments"),
        ).join(
            RepaymentSchedule, RepaymentSchedule.id == RepaymentInstallment.schedule_id
        ).where(RepaymentSchedule.status == "ACTIVE")
        query = self._date_filter(query, RepaymentInstallment.updated_at, filters)
        row = (await self.session.execute(query)).one()
        return [{
            "principal_due": str(row.principal_due),
            "principal_paid": str(row.principal_paid),
            "outstanding_principal": str(row.principal_due - row.principal_paid),
            "installments": row.installments,
        }]

    async def repayments(self, **filters) -> list[dict]:
        query = select(
            RepaymentPayment.status.label("status"),
            func.count(RepaymentPayment.id).label("count"),
            func.coalesce(func.sum(RepaymentPayment.amount), 0).label("amount"),
        )
        query = self._date_filter(query, RepaymentPayment.created_at, filters)
        result = await self.session.execute(
            query.group_by(RepaymentPayment.status).order_by(RepaymentPayment.status)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {"status": row.status, "count": row.count, "amount": str(row.amount)}
            for row in result
        ]

    async def overdue(self, **filters) -> list[dict]:
        query = select(
            CollectionCase.dpd_bucket.label("bucket"),
            func.count(CollectionCase.id).label("cases"),
            func.coalesce(func.sum(CollectionCase.overdue_principal), 0).label("principal"),
        ).where(CollectionCase.status != "CLOSED")
        query = self._date_filter(query, CollectionCase.updated_at, filters)
        result = await self.session.execute(
            query.group_by(CollectionCase.dpd_bucket).order_by(CollectionCase.dpd_bucket)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {"bucket": row.bucket, "cases": row.cases, "overdue_principal": str(row.principal)}
            for row in result
        ]

    async def collections(self, **filters) -> list[dict]:
        query = select(
            CollectionCase.status.label("status"),
            CollectionCase.escalation_level.label("escalation_level"),
            func.count(CollectionCase.id).label("cases"),
            func.coalesce(func.sum(CollectionCase.overdue_principal), 0).label("principal"),
        )
        query = self._date_filter(query, CollectionCase.updated_at, filters)
        result = await self.session.execute(
            query.group_by(CollectionCase.status, CollectionCase.escalation_level)
            .order_by(CollectionCase.status, CollectionCase.escalation_level)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {
                "status": row.status,
                "escalation_level": row.escalation_level,
                "cases": row.cases,
                "overdue_principal": str(row.principal),
            }
            for row in result
        ]

    async def closures(self, **filters) -> list[dict]:
        query = select(
            CollectionCase.close_reason.label("reason"),
            func.count(CollectionCase.id).label("count"),
        ).where(CollectionCase.status == "CLOSED")
        query = self._date_filter(query, CollectionCase.closed_at, filters)
        result = await self.session.execute(
            query.group_by(CollectionCase.close_reason).order_by(CollectionCase.close_reason)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [{"reason": row.reason, "count": row.count} for row in result]

    async def provider_failures(self, **filters) -> list[dict]:
        queries = [
            (
                select(
                    Notification.provider.label("provider"),
                    Notification.failure_code.label("failure_code"),
                    func.count(Notification.id).label("count"),
                ).where(Notification.status.in_(("DELIVERY_FAILED", "DEAD"))),
                Notification.created_at,
            ),
            (
                select(
                    Disbursement.provider.label("provider"),
                    Disbursement.failure_code.label("failure_code"),
                    func.count(Disbursement.id).label("count"),
                ).where(Disbursement.status == "FAILED"),
                Disbursement.created_at,
            ),
            (
                select(
                    RepaymentPayment.provider.label("provider"),
                    RepaymentPayment.failure_code.label("failure_code"),
                    func.count(RepaymentPayment.id).label("count"),
                ).where(RepaymentPayment.status == "FAILED"),
                RepaymentPayment.created_at,
            ),
            (
                select(
                    CreditAssessment.provider.label("provider"),
                    CreditAssessment.failure_reason.label("failure_code"),
                    func.count(CreditAssessment.id).label("count"),
                ).where(CreditAssessment.status == "FAILED"),
                CreditAssessment.created_at,
            ),
            (
                select(
                    FraudAssessment.provider.label("provider"),
                    FraudAssessment.failure_reason.label("failure_code"),
                    func.count(FraudAssessment.id).label("count"),
                ).where(FraudAssessment.status == "FAILED"),
                FraudAssessment.created_at,
            ),
        ]
        rows: list[dict] = []
        for query, created_at in queries:
            query = self._date_filter(query, created_at, filters)
            result = await self.session.execute(
                query.group_by(query.selected_columns.provider, query.selected_columns.failure_code)
            )
            rows.extend(
                {"provider": row.provider, "failure_code": row.failure_code, "count": row.count}
                for row in result
            )
        start = filters["offset"]
        return rows[start : start + filters["limit"] + 1]

    async def reconciliation(self, **filters) -> list[dict]:
        query = select(
            ReconciliationRecord.flow.label("flow"),
            ReconciliationRecord.discrepancy.label("discrepancy"),
            func.count(ReconciliationRecord.id).label("count"),
        ).where(ReconciliationRecord.status != "MATCHED")
        query = self._date_filter(query, ReconciliationRecord.created_at, filters)
        result = await self.session.execute(
            query.group_by(ReconciliationRecord.flow, ReconciliationRecord.discrepancy)
            .order_by(ReconciliationRecord.flow, ReconciliationRecord.discrepancy)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {"flow": row.flow, "discrepancy": row.discrepancy, "count": row.count}
            for row in result
        ]

    async def risk_fraud(self, **filters) -> list[dict]:
        risk = select(
            RiskAssessment.risk_band.label("category"),
            func.count(RiskAssessment.id).label("count"),
        )
        fraud = select(
            FraudAssessment.risk_level.label("category"),
            func.count(FraudAssessment.id).label("count"),
        )
        risk = self._date_filter(risk, RiskAssessment.created_at, filters)
        fraud = self._date_filter(fraud, FraudAssessment.created_at, filters)
        rows = []
        for kind, query, column in (
            ("RISK", risk, RiskAssessment.risk_band),
            ("FRAUD", fraud, FraudAssessment.risk_level),
        ):
            result = await self.session.execute(
                query.group_by(column).order_by(column)
            )
            rows.extend({"type": kind, "category": row.category, "count": row.count} for row in result)
        start = filters["offset"]
        return rows[start : start + filters["limit"] + 1]

    @staticmethod
    def _date_filter(query, column, filters):
        if column is not None and filters["start_at"]:
            query = query.where(column >= filters["start_at"])
        if column is not None and filters["end_at"]:
            query = query.where(column < filters["end_at"])
        return query
