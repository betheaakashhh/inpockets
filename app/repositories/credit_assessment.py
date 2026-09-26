from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_assessment import CreditAssessment


class CreditAssessmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        loan_application_id: UUID,
        user_id: UUID,
        consent_id: UUID,
        provider: str,
        provider_reference: str,
        status: str,
        bureau_score: int | None = None,
        score_type: str | None = None,
        total_accounts: int | None = None,
        active_accounts: int | None = None,
        delinquent_accounts: int | None = None,
        total_outstanding=None,
        recent_inquiries: int | None = None,
        feature_snapshot: dict | None = None,
        provider_report_version: str | None = None,
        requested_at=None,
        received_at=None,
        failure_reason: str | None = None,
    ) -> CreditAssessment:
        assessment = CreditAssessment(
            loan_application_id=loan_application_id,
            user_id=user_id,
            consent_id=consent_id,
            provider=provider,
            provider_reference=provider_reference,
            status=status,
            bureau_score=bureau_score,
            score_type=score_type,
            total_accounts=total_accounts,
            active_accounts=active_accounts,
            delinquent_accounts=delinquent_accounts,
            total_outstanding=total_outstanding,
            recent_inquiries=recent_inquiries,
            feature_snapshot=feature_snapshot,
            provider_report_version=provider_report_version,
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
    ) -> CreditAssessment | None:
        result = await self.session.execute(
            select(CreditAssessment).where(
                CreditAssessment.id == assessment_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_reference(
        self,
        *,
        provider: str,
        provider_reference: str,
    ) -> CreditAssessment | None:
        result = await self.session.execute(
            select(CreditAssessment).where(
                CreditAssessment.provider == provider,
                CreditAssessment.provider_reference == provider_reference,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_loan_application(
        self,
        loan_application_id: UUID,
    ) -> list[CreditAssessment]:
        result = await self.session.execute(
            select(CreditAssessment)
            .where(
                CreditAssessment.loan_application_id
                == loan_application_id
            )
            .order_by(CreditAssessment.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_user(
        self,
        user_id: UUID,
    ) -> list[CreditAssessment]:
        result = await self.session.execute(
            select(CreditAssessment)
            .where(CreditAssessment.user_id == user_id)
            .order_by(CreditAssessment.created_at.asc())
        )
        return list(result.scalars().all())