from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, String, case, exists, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ledger import (
    BANK,
    INTEREST_INCOME,
    LOAN_PRINCIPAL,
    PENAL_INCOME,
    UNAPPLIED_RECEIPTS,
)
from app.models.collection import CollectionCase
from app.models.credit_assessment import CreditAssessment
from app.models.disbursement import Disbursement
from app.models.fraud_assessment import FraudAssessment
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerTransaction
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
        rows = await self._grouped(
            LoanApplication, LoanApplication.status, **filters
        )
        return [
            {**row, "as_of": "current", "historical": False}
            for row in rows
        ]

    async def decisions(self, **filters) -> list[dict]:
        query = select(
            LoanDecision.decision_route.label("route"),
            func.count(LoanDecision.id).label("count"),
        ).join(
            LoanApplication, LoanApplication.id == LoanDecision.loan_application_id
        )
        query = self._date_filter(query, LoanDecision.created_at, filters)
        result = await self.session.execute(
            query.group_by(LoanDecision.decision_route)
            .order_by(LoanDecision.decision_route)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {
                "route": row.route,
                "count": row.count,
                "historical": True,
            }
            for row in result
        ]

    async def disbursements(self, **filters) -> list[dict]:
        # Aggregate the bank lines before joining to operational payout rows.
        # A disbursement reversal has the same source id as its original
        # transaction, so this produces one net cash figure per attempt.
        bank_movement = case(
            (LedgerEntry.direction == "DEBIT", LedgerEntry.amount),
            else_=-LedgerEntry.amount,
        )
        ledger_by_disbursement = (
            select(
                LedgerTransaction.source_id.label("disbursement_id"),
                func.coalesce(
                    func.sum(
                        case(
                            (LedgerAccount.code == BANK, -bank_movement),
                            else_=0,
                        )
                    ),
                    0,
                ).label("net_disbursed_amount"),
            )
            .select_from(LedgerTransaction)
            .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerTransaction.source_type == "disbursement")
            .group_by(LedgerTransaction.source_id)
            .subquery()
        )
        query = select(
            Disbursement.status.label("status"),
            func.count(Disbursement.id).label("count"),
            # `amount` remains for existing clients. It is an operational
            # attempt total, not a cash-disbursed total.
            func.coalesce(func.sum(Disbursement.amount), 0).label("attempted_amount"),
            func.coalesce(
                func.sum(
                    case(
                        (Disbursement.status == "FAILED", Disbursement.amount),
                        else_=0,
                    )
                ),
                0,
            ).label("failed_amount"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Disbursement.status.in_(("SUCCESS", "REVERSED")),
                            Disbursement.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("gross_successful_amount"),
            func.coalesce(
                func.sum(
                    case(
                        (Disbursement.status == "REVERSED", Disbursement.amount),
                        else_=0,
                    )
                ),
                0,
            ).label("reversed_amount"),
            func.coalesce(func.sum(ledger_by_disbursement.c.net_disbursed_amount), 0).label(
                "net_disbursed_amount"
            ),
        ).outerjoin(
            ledger_by_disbursement,
            ledger_by_disbursement.c.disbursement_id == Disbursement.id,
        )
        query = self._date_filter(query, Disbursement.created_at, filters)
        result = await self.session.execute(
            query.group_by(Disbursement.status).order_by(Disbursement.status)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {
                "status": row.status,
                "count": row.count,
                "amount": str(row.attempted_amount),
                "attempted_amount": str(row.attempted_amount),
                "failed_amount": str(row.failed_amount),
                "gross_successful_amount": str(row.gross_successful_amount),
                "reversed_amount": str(row.reversed_amount),
                "net_disbursed_amount": str(row.net_disbursed_amount),
                "financial_basis": "ledger_bank_clearing",
            }
            for row in result
        ]

    async def exposure(self, **filters) -> list[dict]:
        schedule_query = select(
            func.coalesce(func.sum(RepaymentSchedule.principal_total), 0).label(
                "principal_due"
            ),
        ).where(RepaymentSchedule.status == "ACTIVE")
        installment_query = select(
            func.coalesce(func.sum(RepaymentInstallment.interest_due), 0).label(
                "interest_due"
            ),
            func.coalesce(func.sum(RepaymentInstallment.fee_due), 0).label("fee_due"),
            func.count(RepaymentInstallment.id).label("installments"),
        ).join(
            RepaymentSchedule,
            RepaymentSchedule.id == RepaymentInstallment.schedule_id,
        ).where(RepaymentSchedule.status == "ACTIVE")
        schedule_row = (await self.session.execute(schedule_query)).one()
        installment_row = (await self.session.execute(installment_query)).one()

        # Asset-account balance is debit minus credit.  Do not join schedules:
        # an offer can retain CANCELLED historical schedules, which would
        # multiply every ledger entry.  EXISTS only establishes eligibility.
        ledger_balance = case(
            (LedgerEntry.direction == "DEBIT", LedgerEntry.amount),
            else_=-LedgerEntry.amount,
        )
        has_active_schedule = exists(
            select(RepaymentSchedule.id).where(
                RepaymentSchedule.loan_offer_id == LedgerTransaction.loan_offer_id,
                RepaymentSchedule.status == "ACTIVE",
            )
        )
        ledger_query = select(
            func.coalesce(func.sum(ledger_balance), 0).label("outstanding_principal"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            LedgerTransaction.kind.in_(
                                ("ADJUSTMENT", "ADJUSTMENT_REVERSAL")
                            ),
                            ledger_balance,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("adjustment_activity"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            LedgerTransaction.kind.in_(("REPAYMENT", "REPAYMENT_REVERSAL")),
                            -ledger_balance,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("net_repayment_principal_reduction"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            LedgerTransaction.kind.in_(
                                ("DISBURSEMENT", "DISBURSEMENT_REVERSAL")
                            ),
                            ledger_balance,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("net_disbursed_principal"),
        ).select_from(LedgerEntry).join(
            LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id
        ).join(
            LedgerAccount, LedgerAccount.id == LedgerEntry.account_id
        ).where(
            LedgerAccount.code == LOAN_PRINCIPAL,
            has_active_schedule,
        )
        ledger_row = (await self.session.execute(ledger_query)).one()
        schedule_to_ledger_variance = ledger_row.outstanding_principal - (
            schedule_row.principal_due
            - ledger_row.net_repayment_principal_reduction
            + ledger_row.adjustment_activity
        )
        accounting_formula_variance = ledger_row.outstanding_principal - (
            ledger_row.net_disbursed_principal
            - ledger_row.net_repayment_principal_reduction
            + ledger_row.adjustment_activity
        )
        return [{
            "principal_due": str(schedule_row.principal_due),
            # Compatibility field: this is now the ledger-derived repayment
            # reduction, never scheduled principal minus the current balance.
            "principal_paid": str(ledger_row.net_repayment_principal_reduction),
            "outstanding_principal": str(ledger_row.outstanding_principal),
            "interest_due": str(installment_row.interest_due),
            "fee_due": str(installment_row.fee_due),
            "installments": installment_row.installments,
            "ledger_adjustment_activity": str(ledger_row.adjustment_activity),
            "net_repayment_principal_reduction": str(
                ledger_row.net_repayment_principal_reduction
            ),
            "net_disbursed_principal": str(ledger_row.net_disbursed_principal),
            "adjustment_principal_effect": str(ledger_row.adjustment_activity),
            "schedule_to_ledger_variance": str(schedule_to_ledger_variance),
            "accounting_formula_variance": str(accounting_formula_variance),
            "as_of": "current",
            "historical": False,
        }]

    async def repayments(self, **filters) -> list[dict]:
        # Repayment rows are operational state.  Financial quantities come
        # from the per-payment ledger aggregate so an exact reversal cancels
        # the original posting rather than leaving allocations in the report.
        bank_movement = case(
            (LedgerEntry.direction == "DEBIT", LedgerEntry.amount),
            else_=-LedgerEntry.amount,
        )
        credit_movement = case(
            (LedgerEntry.direction == "CREDIT", LedgerEntry.amount),
            else_=-LedgerEntry.amount,
        )
        ledger_by_payment = (
            select(
                LedgerTransaction.source_id.label("payment_id"),
                func.coalesce(
                    func.sum(
                        case((LedgerAccount.code == BANK, bank_movement), else_=0)
                    ),
                    0,
                ).label("retained_net_amount"),
                func.coalesce(
                    func.sum(
                        case((LedgerAccount.code == LOAN_PRINCIPAL, credit_movement), else_=0)
                    ),
                    0,
                ).label("principal_applied"),
                func.coalesce(
                    func.sum(
                        case((LedgerAccount.code == INTEREST_INCOME, credit_movement), else_=0)
                    ),
                    0,
                ).label("interest_applied"),
                func.coalesce(
                    func.sum(
                        case((LedgerAccount.code == PENAL_INCOME, credit_movement), else_=0)
                    ),
                    0,
                ).label("fee_applied"),
                func.coalesce(
                    func.sum(
                        case((LedgerAccount.code == UNAPPLIED_RECEIPTS, credit_movement), else_=0)
                    ),
                    0,
                ).label("unapplied_amount"),
            )
            .select_from(LedgerTransaction)
            .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerTransaction.source_type == "repayment_payment")
            .group_by(LedgerTransaction.source_id)
            .subquery()
        )
        query = select(
            RepaymentPayment.status.label("status"),
            func.count(RepaymentPayment.id).label("count"),
            func.coalesce(func.sum(RepaymentPayment.amount), 0).label("attempted_amount"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            RepaymentPayment.status.in_(("SUCCESS", "REVERSED")),
                            RepaymentPayment.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("gross_successful_amount"),
            func.coalesce(func.sum(ledger_by_payment.c.retained_net_amount), 0).label(
                "retained_net_amount"
            ),
            func.coalesce(func.sum(ledger_by_payment.c.principal_applied), 0).label(
                "principal_applied"
            ),
            func.coalesce(func.sum(ledger_by_payment.c.interest_applied), 0).label(
                "interest_applied"
            ),
            func.coalesce(func.sum(ledger_by_payment.c.fee_applied), 0).label("fee_applied"),
            func.coalesce(func.sum(ledger_by_payment.c.unapplied_amount), 0).label(
                "unapplied_amount"
            ),
        ).outerjoin(
            ledger_by_payment,
            ledger_by_payment.c.payment_id == RepaymentPayment.id,
        )
        query = self._date_filter(query, RepaymentPayment.created_at, filters)
        result = await self.session.execute(
            query.group_by(RepaymentPayment.status).order_by(RepaymentPayment.status)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {
                "status": row.status,
                "count": row.count,
                "attempted_amount": str(row.attempted_amount),
                "gross_successful_amount": str(row.gross_successful_amount),
                "retained_net_amount": str(row.retained_net_amount),
                "confirmed_amount": str(row.retained_net_amount),
                "principal_applied": str(row.principal_applied),
                "interest_applied": str(row.interest_applied),
                "fee_applied": str(row.fee_applied),
                "unapplied_amount": str(row.unapplied_amount),
                "net_principal_applied": str(row.principal_applied),
                "net_interest_applied": str(row.interest_applied),
                "net_fee_applied": str(row.fee_applied),
                "net_unapplied_amount": str(row.unapplied_amount),
                "financial_basis": "ledger_postings",
            }
            for row in result
        ]

    async def overdue(self, **filters) -> list[dict]:
        query = select(
            CollectionCase.dpd_bucket.label("bucket"),
            func.count(CollectionCase.id).label("cases"),
            func.coalesce(func.sum(CollectionCase.overdue_principal), 0).label("principal"),
        ).where(CollectionCase.status != "CLOSED")
        result = await self.session.execute(
            query.group_by(CollectionCase.dpd_bucket).order_by(CollectionCase.dpd_bucket)
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        rows = [
            {
                "metric": "current",
                "bucket": row.bucket,
                "cases": row.cases,
                "overdue_principal": str(row.principal),
            }
            for row in result
        ]
        return rows

    async def collections(self, **filters) -> list[dict]:
        if filters["start_at"] or filters["end_at"]:
            opened = select(
                func.count(CollectionCase.id).label("cases"),
            )
            opened = self._date_filter(opened, CollectionCase.opened_at, filters)
            opened_row = (await self.session.execute(opened)).one()
            closed = select(
                func.count(CollectionCase.id).label("cases"),
            ).where(CollectionCase.closed_at.is_not(None))
            closed = self._date_filter(closed, CollectionCase.closed_at, filters)
            closed_row = (await self.session.execute(closed)).one()
            period_rows = [
                {
                    "metric": "opened_in_period",
                    "cases": opened_row.cases,
                },
                {
                    "metric": "closed_in_period",
                    "cases": closed_row.cases,
                },
            ]
            start = filters["offset"]
            return period_rows[start : start + filters["limit"] + 1]

        current_query = select(
            CollectionCase.status.label("status"),
            CollectionCase.escalation_level.label("escalation_level"),
            func.count(CollectionCase.id).label("cases"),
            func.coalesce(func.sum(CollectionCase.overdue_principal), 0).label("principal"),
        )
        current_query = current_query.group_by(
            CollectionCase.status, CollectionCase.escalation_level
        ).order_by(CollectionCase.status, CollectionCase.escalation_level)
        result = await self.session.execute(
            current_query.offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        rows = [
            {
                "metric": "current",
                "status": row.status,
                "escalation_level": row.escalation_level,
                "cases": row.cases,
                "overdue_principal": str(row.principal),
            }
            for row in result
        ]
        return rows[: filters["offset"] + filters["limit"] + 1]

    async def closures(self, **filters) -> list[dict]:
        return [{
            "supported": False,
            "metric": "loan_closures",
            "reason": (
                "No authoritative loan-closure record exists; collection-case "
                "closures are intentionally not reported as loan closures."
            ),
        }]

    async def provider_failures(self, **filters) -> list[dict]:
        sources = [
            select(
                Notification.provider.label("provider"),
                Notification.failure_code.label("failure_code"),
                Notification.created_at.label("created_at"),
            ).where(Notification.status.in_(("DELIVERY_FAILED", "DEAD"))),
            select(
                Disbursement.provider,
                Disbursement.failure_code,
                Disbursement.created_at,
            ).where(Disbursement.status == "FAILED"),
            select(
                RepaymentPayment.provider,
                RepaymentPayment.failure_code,
                RepaymentPayment.created_at,
            ).where(RepaymentPayment.status == "FAILED"),
            select(
                CreditAssessment.provider,
                CreditAssessment.failure_reason,
                CreditAssessment.created_at,
            ).where(CreditAssessment.status == "FAILED"),
            select(
                FraudAssessment.provider,
                FraudAssessment.failure_reason,
                FraudAssessment.created_at,
            ).where(FraudAssessment.status == "FAILED"),
        ]
        filtered = [
            self._date_filter(query, query.selected_columns.created_at, filters)
            for query in sources
        ]
        failures = union_all(*filtered).subquery()
        query = (
            select(
                failures.c.provider,
                failures.c.failure_code,
                func.count().label("count"),
            )
            .group_by(failures.c.provider, failures.c.failure_code)
            .order_by(failures.c.provider, failures.c.failure_code)
            .offset(filters["offset"])
            .limit(filters["limit"] + 1)
        )
        result = await self.session.execute(query)
        return [
            {"provider": row.provider, "failure_code": row.failure_code, "count": row.count}
            for row in result
        ]

    async def reconciliation(self, **filters) -> list[dict]:
        amount_comparable = (
            ReconciliationRecord.internal_amount.is_not(None)
            & ReconciliationRecord.external_amount.is_not(None)
        )
        ledger_comparable = (
            ReconciliationRecord.ledger_net.is_not(None)
            & ReconciliationRecord.expected_ledger_net.is_not(None)
        )
        query = select(
            ReconciliationRecord.flow.label("flow"),
            ReconciliationRecord.status.label("status"),
            ReconciliationRecord.discrepancy.label("discrepancy"),
            func.count(ReconciliationRecord.id).label("count"),
            func.count(ReconciliationRecord.internal_amount).label("internal_amount_count"),
            func.sum(ReconciliationRecord.internal_amount).label("internal_amount_total"),
            func.count(ReconciliationRecord.external_amount).label("external_amount_count"),
            func.sum(ReconciliationRecord.external_amount).label("external_amount_total"),
            func.count().filter(amount_comparable).label("amount_comparison_count"),
            func.sum(
                case(
                    (
                        amount_comparable,
                        ReconciliationRecord.external_amount - ReconciliationRecord.internal_amount,
                    ),
                    else_=None,
                )
            ).label("external_minus_internal_total"),
            func.count(ReconciliationRecord.ledger_net).label("ledger_net_count"),
            func.sum(ReconciliationRecord.ledger_net).label("ledger_net_total"),
            func.count(ReconciliationRecord.expected_ledger_net).label(
                "expected_ledger_net_count"
            ),
            func.sum(ReconciliationRecord.expected_ledger_net).label(
                "expected_ledger_net_total"
            ),
            func.count().filter(ledger_comparable).label("ledger_comparison_count"),
            func.sum(
                case(
                    (
                        ledger_comparable,
                        ReconciliationRecord.ledger_net
                        - ReconciliationRecord.expected_ledger_net,
                    ),
                    else_=None,
                )
            ).label("ledger_minus_expected_total"),
        ).where(ReconciliationRecord.status != "MATCHED")
        query = self._date_filter(query, ReconciliationRecord.created_at, filters)
        result = await self.session.execute(
            query.group_by(
                ReconciliationRecord.flow,
                ReconciliationRecord.status,
                ReconciliationRecord.discrepancy,
            )
            .order_by(
                ReconciliationRecord.flow,
                ReconciliationRecord.status,
                ReconciliationRecord.discrepancy,
            )
            .offset(filters["offset"]).limit(filters["limit"] + 1)
        )
        return [
            {
                "flow": row.flow,
                "status": row.status,
                "discrepancy": row.discrepancy,
                "count": row.count,
                "internal_amount_count": row.internal_amount_count,
                "internal_amount_total": self._amount(row.internal_amount_total),
                "external_amount_count": row.external_amount_count,
                "external_amount_total": self._amount(row.external_amount_total),
                "amount_comparison_count": row.amount_comparison_count,
                "external_minus_internal_total": self._amount(
                    row.external_minus_internal_total
                ),
                "ledger_net_count": row.ledger_net_count,
                "ledger_net_total": self._amount(row.ledger_net_total),
                "expected_ledger_net_count": row.expected_ledger_net_count,
                "expected_ledger_net_total": self._amount(row.expected_ledger_net_total),
                "ledger_comparison_count": row.ledger_comparison_count,
                "ledger_minus_expected_total": self._amount(row.ledger_minus_expected_total),
            }
            for row in result
        ]

    async def risk_fraud(self, **filters) -> list[dict]:
        risk_ranked = select(
            RiskAssessment.loan_application_id,
            RiskAssessment.risk_band.label("category"),
            RiskAssessment.status,
            RiskAssessment.created_at,
            RiskAssessment.id,
            func.row_number().over(
                partition_by=RiskAssessment.loan_application_id,
                order_by=(RiskAssessment.created_at.desc(), RiskAssessment.id.desc()),
            ).label("row_number"),
        ).subquery()
        fraud_ranked = select(
            FraudAssessment.loan_application_id,
            FraudAssessment.risk_level.label("category"),
            FraudAssessment.status,
            FraudAssessment.created_at,
            FraudAssessment.id,
            func.row_number().over(
                partition_by=FraudAssessment.loan_application_id,
                order_by=(FraudAssessment.created_at.desc(), FraudAssessment.id.desc()),
            ).label("row_number"),
        ).subquery()
        risk = select(
            risk_ranked.c.category,
            risk_ranked.c.status,
            func.count().label("count"),
        ).where(risk_ranked.c.row_number == 1)
        fraud = select(
            fraud_ranked.c.category,
            fraud_ranked.c.status,
            func.count().label("count"),
        ).where(fraud_ranked.c.row_number == 1)
        risk = self._date_filter(risk, risk_ranked.c.created_at, filters)
        fraud = self._date_filter(fraud, fraud_ranked.c.created_at, filters)
        combined = union_all(
            select(
                risk.selected_columns.category,
                risk.selected_columns.status,
                func.cast("RISK", String).label("type"),
                risk.selected_columns.count,
            )
            .group_by(risk.selected_columns.category, risk.selected_columns.status)
            .order_by(None),
            select(
                fraud.selected_columns.category,
                fraud.selected_columns.status,
                func.cast("FRAUD", String).label("type"),
                fraud.selected_columns.count,
            )
            .group_by(fraud.selected_columns.category, fraud.selected_columns.status)
            .order_by(None),
        ).subquery()
        query = (
            select(
                combined.c.type,
                combined.c.category,
                combined.c.status,
                combined.c.count,
            )
            .order_by(combined.c.type, combined.c.category, combined.c.status)
            .offset(filters["offset"])
            .limit(filters["limit"] + 1)
        )
        result = await self.session.execute(query)
        return [
            {
                "type": row.type,
                "category": row.category,
                "status": row.status,
                "count": row.count,
            }
            for row in result
        ]

    @staticmethod
    def _date_filter(query, column, filters):
        if column is not None and filters["start_at"]:
            query = query.where(column >= filters["start_at"])
        if column is not None and filters["end_at"]:
            query = query.where(column < filters["end_at"])
        return query

    @staticmethod
    def _amount(value) -> str | None:
        """Keep an unavailable financial aggregate distinct from a zero amount."""
        return None if value is None else str(value)
