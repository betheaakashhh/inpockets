from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.domain.affordability import (
    AffordabilityAssessmentResult,
    AffordabilityAssessmentStatus,
    AffordabilityFactors,
    AffordabilitySourceType,
)
from app.models.loan_application import LoanApplication
from app.repositories.affordability_assessment import (
    AffordabilityAssessmentRepository,
)


class AffordabilityAssessmentService:
    """Creates deterministic affordability assessment results."""

    CALCULATION_VERSION = "affordability-v1"

    def __init__(self, session):
        self.session = session
        self.repository = AffordabilityAssessmentRepository(session)

    async def assess(
        self,
        *,
        user_id: UUID,
        application: LoanApplication,
        monthly_income: Decimal,
        monthly_obligations: Decimal,
        source_type: AffordabilitySourceType = (
            AffordabilitySourceType.CUSTOMER_DECLARED
        ),
        source_reference: str = "internal",
        requested_at: datetime | None = None,
    ) -> AffordabilityAssessmentResult:
        if application.user_id != user_id:
            raise ValueError("loan application does not belong to user")

        if monthly_income <= Decimal("0"):
            raise ValueError("monthly_income must be greater than zero")

        if monthly_obligations < Decimal("0"):
            raise ValueError("monthly_obligations cannot be negative")

        if application.requested_amount <= Decimal("0"):
            raise ValueError("requested_amount must be greater than zero")

        if application.requested_tenure_days <= 0:
            raise ValueError(
                "requested_tenure_days must be greater than zero"
            )

        existing = await self.repository.get_latest_for_loan_application(
            application.id
        )

        if (
            existing is not None
            and existing.status
            == AffordabilityAssessmentStatus.COMPLETED.value
            and existing.calculation_version == self.CALCULATION_VERSION
        ):
            return self._to_result(existing)

        requested_at = requested_at or datetime.now(timezone.utc)

        disposable_monthly_income = (
            monthly_income - monthly_obligations
        )

        existing_obligation_ratio = (
            monthly_obligations / monthly_income
        )

        feature_snapshot = {
            "monthly_income": str(monthly_income),
            "monthly_obligations": str(monthly_obligations),
            "requested_amount": str(application.requested_amount),
            "requested_tenure_days": application.requested_tenure_days,
            "disposable_monthly_income": str(
                disposable_monthly_income
            ),
            "existing_obligation_ratio": str(
                existing_obligation_ratio
            ),
        }

        assessment = await self.repository.create(
            loan_application_id=application.id,
            user_id=user_id,
            source_type=source_type.value,
            source_reference=source_reference,
            status=AffordabilityAssessmentStatus.COMPLETED.value,
            monthly_income=monthly_income,
            monthly_obligations=monthly_obligations,
            requested_amount=application.requested_amount,
            requested_tenure_days=application.requested_tenure_days,
            disposable_monthly_income=disposable_monthly_income,
            existing_obligation_ratio=existing_obligation_ratio,
            feature_snapshot=feature_snapshot,
            calculation_version=self.CALCULATION_VERSION,
            requested_at=requested_at,
            completed_at=requested_at,
        )

        return self._to_result(assessment)

    @staticmethod
    def _to_result(assessment) -> AffordabilityAssessmentResult:
        factors = AffordabilityFactors(
            monthly_income=assessment.monthly_income,
            monthly_obligations=assessment.monthly_obligations,
            requested_amount=assessment.requested_amount,
            requested_tenure_days=assessment.requested_tenure_days,
            disposable_monthly_income=assessment.disposable_monthly_income,
            existing_obligation_ratio=assessment.existing_obligation_ratio,
        )

        return AffordabilityAssessmentResult(
            source_type=AffordabilitySourceType(assessment.source_type),
            source_reference=assessment.source_reference,
            status=AffordabilityAssessmentStatus(assessment.status),
            factors=factors,
            failure_reason=assessment.failure_reason,
        )
