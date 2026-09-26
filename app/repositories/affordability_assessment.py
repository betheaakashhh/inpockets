from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.affordability_assessment import AffordabilityAssessment


class AffordabilityAssessmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        source_type: str,
        source_reference: str,
        status: str,
        monthly_income=None,
        monthly_obligations=None,
        requested_amount=None,
        requested_tenure_days=None,
        disposable_monthly_income=None,
        existing_obligation_ratio=None,
        feature_snapshot=None,
        calculation_version=None,
        requested_at=None,
        completed_at=None,
        failure_reason=None,
    ) -> AffordabilityAssessment:
        assessment = AffordabilityAssessment(
            loan_application_id=loan_application_id,
            user_id=user_id,
            source_type=source_type,
            source_reference=source_reference,
            status=status,
            monthly_income=monthly_income,
            monthly_obligations=monthly_obligations,
            requested_amount=requested_amount,
            requested_tenure_days=requested_tenure_days,
            disposable_monthly_income=disposable_monthly_income,
            existing_obligation_ratio=existing_obligation_ratio,
            feature_snapshot=feature_snapshot,
            calculation_version=calculation_version,
            requested_at=requested_at,
            completed_at=completed_at,
            failure_reason=failure_reason,
        )

        self.session.add(assessment)
        await self.session.flush()

        return assessment

    async def get_by_id(
        self,
        assessment_id: UUID,
    ) -> AffordabilityAssessment | None:
        result = await self.session.execute(
            select(AffordabilityAssessment).where(
                AffordabilityAssessment.id == assessment_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[AffordabilityAssessment]:
        result = await self.session.execute(
            select(AffordabilityAssessment)
            .where(
                AffordabilityAssessment.loan_application_id
                == loan_application_id
            )
            .order_by(
                AffordabilityAssessment.created_at.asc(),
                AffordabilityAssessment.id.asc(),
            )
        )

        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
    ) -> list[AffordabilityAssessment]:
        result = await self.session.execute(
            select(AffordabilityAssessment)
            .where(
                AffordabilityAssessment.user_id == user_id
            )
            .order_by(
                AffordabilityAssessment.created_at.asc(),
                AffordabilityAssessment.id.asc(),
            )
        )

        return list(result.scalars().all())

    async def get_latest_for_loan_application(
    self,
    loan_application_id: UUID,
    ):
        result = await self.session.execute(
            select(AffordabilityAssessment)
            .where(
                AffordabilityAssessment.loan_application_id
                == loan_application_id
            )
            .order_by(
                AffordabilityAssessment.requested_at.desc(),
                AffordabilityAssessment.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()