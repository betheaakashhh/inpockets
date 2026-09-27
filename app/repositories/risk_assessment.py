from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk_assessment import RiskAssessment


class RiskAssessmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        model_version: str,
        status: str,
        risk_band: str,
        recommended_action: str,
        risk_score=None,
        recommended_amount=None,
        max_eligible_amount=None,
        factors: list | None = None,
        flags: list | None = None,
        failure_reason: str | None = None,
    ) -> RiskAssessment:
        assessment = RiskAssessment(
            loan_application_id=loan_application_id,
            user_id=user_id,
            model_version=model_version,
            status=status,
            risk_score=risk_score,
            risk_band=risk_band,
            recommended_action=recommended_action,
            recommended_amount=recommended_amount,
            max_eligible_amount=max_eligible_amount,
            factors=factors,
            flags=flags,
            failure_reason=failure_reason,
        )

        self.session.add(assessment)
        await self.session.flush()

        return assessment

    async def get_by_id(
        self,
        assessment_id: UUID,
    ) -> RiskAssessment | None:
        result = await self.session.execute(
            select(RiskAssessment).where(
                RiskAssessment.id == assessment_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[RiskAssessment]:
        result = await self.session.execute(
            select(RiskAssessment)
            .where(
                RiskAssessment.loan_application_id == loan_application_id
            )
            .order_by(
                RiskAssessment.created_at.asc(),
                RiskAssessment.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
    ) -> list[RiskAssessment]:
        result = await self.session.execute(
            select(RiskAssessment)
            .where(RiskAssessment.user_id == user_id)
            .order_by(
                RiskAssessment.created_at.asc(),
                RiskAssessment.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_latest_for_loan_application(
        self,
        loan_application_id: UUID,
    ) -> RiskAssessment | None:
        result = await self.session.execute(
            select(RiskAssessment)
            .where(
                RiskAssessment.loan_application_id == loan_application_id
            )
            .order_by(
                RiskAssessment.created_at.desc(),
                RiskAssessment.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
