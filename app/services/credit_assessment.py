from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.domain.credit import CreditAssessmentResult, CreditAssessmentStatus
from app.models.credit_assessment import CreditAssessment
from app.providers.credit_bureau import CreditBureauProvider
from app.repositories.credit_assessment import CreditAssessmentRepository


class CreditAssessmentService:
    def __init__(
        self,
        *,
        repository: CreditAssessmentRepository,
        provider: CreditBureauProvider,
    ):
        self.repository = repository
        self.provider = provider

    async def assess(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
        consent_id: UUID,
    ) -> CreditAssessment:
        """
        Request a credit assessment from the configured bureau provider
        and persist the provider result as an immutable historical snapshot.
        """

        existing = await self.repository.list_by_loan_application(
            application_id,
        )

        # If a completed assessment already exists, return it rather than
        # creating another provider request.
        for assessment in reversed(existing):
            if assessment.status == CreditAssessmentStatus.COMPLETED:
                return assessment

        requested_at = datetime.now(timezone.utc)

        try:
            result = await self.provider.assess_credit(
                user_id=user_id,
                application_id=application_id,
                consent_reference=str(consent_id),
            )
        except asyncio.TimeoutError:
            result = CreditAssessmentResult(
                provider="unknown",
                provider_reference=f"timeout-{application_id}-{uuid4().hex}",
                status=CreditAssessmentStatus.FAILED,
                failure_reason="credit provider timeout",
            )

        report = result.report

        assessment = await self.repository.create(
            loan_application_id=application_id,
            user_id=user_id,
            consent_id=consent_id,
            provider=result.provider,
            provider_reference=result.provider_reference,
            status=result.status,
            bureau_score=report.score if report else None,
            score_type=report.score_type if report else None,
            total_accounts=report.total_accounts if report else None,
            active_accounts=report.active_accounts if report else None,
            delinquent_accounts=report.delinquent_accounts if report else None,
            total_outstanding=(
                report.total_outstanding if report else None
            ),
            recent_inquiries=(
                report.recent_inquiries if report else None
            ),
            feature_snapshot=self._build_feature_snapshot(report),
            requested_at=requested_at,
            received_at=(
                report.report_received_at
                if report and report.report_received_at
                else datetime.now(timezone.utc)
            ),
            failure_reason=result.failure_reason,
        )

        return assessment

    @staticmethod
    def _build_feature_snapshot(report):
        if report is None:
            return None

        return {
            "total_accounts": report.total_accounts,
            "active_accounts": report.active_accounts,
            "delinquent_accounts": report.delinquent_accounts,
            "total_outstanding": (
                str(report.total_outstanding)
                if report.total_outstanding is not None
                else None
            ),
            "recent_inquiries": report.recent_inquiries,
        }