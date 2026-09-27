from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fraud_assessment import FraudAssessment


class FraudAssessmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        provider: str,
        provider_reference: str,
        status: str,
        risk_level: str,
        signals: list | None = None,
        model_version: str | None = None,
        requested_at=None,
        received_at=None,
        failure_reason: str | None = None,
    ) -> FraudAssessment:
        assessment = FraudAssessment(
            loan_application_id=loan_application_id,
            user_id=user_id,
            provider=provider,
            provider_reference=provider_reference,
            status=status,
            risk_level=risk_level,
            signals=signals,
            model_version=model_version,
            requested_at=requested_at,
            received_at=received_at,
            failure_reason=failure_reason,
        )

        self.session.add(assessment)
        await self.session.flush()

        return assessment

    async def get_by_id(
        self,
        assessment_id: UUID,
    ) -> FraudAssessment | None:
        result = await self.session.execute(
            select(FraudAssessment).where(
                FraudAssessment.id == assessment_id
            )
        )

        return result.scalar_one_or_none()

    async def get_by_provider_reference(
        self,
        *,
        provider: str,
        provider_reference: str,
    ) -> FraudAssessment | None:
        result = await self.session.execute(
            select(FraudAssessment).where(
                FraudAssessment.provider == provider,
                FraudAssessment.provider_reference == provider_reference,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[FraudAssessment]:
        result = await self.session.execute(
            select(FraudAssessment)
            .where(
                FraudAssessment.loan_application_id == loan_application_id
            )
            .order_by(FraudAssessment.created_at.asc())
        )

        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
    ) -> list[FraudAssessment]:
        result = await self.session.execute(
            select(FraudAssessment)
            .where(FraudAssessment.user_id == user_id)
            .order_by(FraudAssessment.created_at.asc())
        )

        return list(result.scalars().all())