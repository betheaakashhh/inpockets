from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.domain.assessment import AssessmentContext
from app.domain.risk import RiskEngineInput
from app.models.loan_application import LoanApplication
from app.repositories.risk_assessment import RiskAssessmentRepository


class AssessmentOrchestrator:
    """
    Coordinates credit, fraud, affordability, and risk assessment.

    Component services own provider interaction and their own persistence.
    The risk engine remains a deterministic domain component.
    """

    def __init__(
        self,
        *,
        credit_service,
        fraud_service,
        affordability_service,
        risk_engine,
        risk_repository: RiskAssessmentRepository,
    ):
        self.credit_service = credit_service
        self.fraud_service = fraud_service
        self.affordability_service = affordability_service
        self.risk_engine = risk_engine
        self.risk_repository = risk_repository

    async def assess(
        self,
        *,
        context: AssessmentContext,
        application: LoanApplication,
        consent_id: UUID,
        monthly_income: Decimal,
        monthly_obligations: Decimal,
    ):
        if application.id != context.loan_application_id:
            raise ValueError(
                "assessment context does not match loan application"
            )

        if application.user_id != context.user_id:
            raise ValueError(
                "loan application does not belong to user"
            )

        latest_risk = (
            await self.risk_repository.get_latest_for_loan_application(
                application.id
            )
        )

        if latest_risk is not None:
            return latest_risk

        credit = await self.credit_service.assess(
            user_id=context.user_id,
            application_id=application.id,
            consent_id=consent_id,
        )

        fraud = await self.fraud_service.assess(
            user_id=context.user_id,
            application_id=application.id,
        )

        affordability = await self.affordability_service.assess(
            user_id=context.user_id,
            application=application,
            monthly_income=monthly_income,
            monthly_obligations=monthly_obligations,
        )

        factors = affordability.factors

        risk_input = RiskEngineInput(
            credit_score=credit.bureau_score,
            delinquent_accounts=credit.delinquent_accounts,
            recent_inquiries=credit.recent_inquiries,
            fraud_risk_level=fraud.risk_level,
            monthly_income=(
                factors.monthly_income
                if factors
                else None
            ),
            monthly_obligations=(
                factors.monthly_obligations
                if factors
                else None
            ),
            disposable_monthly_income=(
                factors.disposable_monthly_income
                if factors
                else None
            ),
            existing_obligation_ratio=(
                factors.existing_obligation_ratio
                if factors
                else None
            ),
            requested_amount=context.requested_amount,
            requested_tenure_days=context.requested_tenure_days,
        )

        risk_result = self.risk_engine.assess(risk_input)

        return await self.risk_repository.create(
            loan_application_id=application.id,
            user_id=context.user_id,
            model_version=risk_result.model_version,
            status=risk_result.status.value,
            risk_score=risk_result.risk_score,
            risk_band=risk_result.risk_band.value,
            recommended_action=risk_result.recommended_action.value,
            recommended_amount=risk_result.recommended_amount,
            max_eligible_amount=risk_result.max_eligible_amount,
            factors=[
                {
                    "code": factor.code,
                    "description": factor.description,
                    "category": factor.category,
                    "impact": factor.impact,
                    "value": factor.value,
                }
                for factor in risk_result.factors
            ],
            flags=[
                {
                    "code": flag.code,
                    "description": flag.description,
                    "severity": flag.severity,
                }
                for flag in risk_result.flags
            ],
            failure_reason=risk_result.failure_reason,
        )