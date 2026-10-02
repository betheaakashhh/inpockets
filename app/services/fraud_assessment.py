from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.domain.fraud import (
    FraudAssessmentResult,
    FraudAssessmentStatus,
    FraudRiskLevel,
)
from app.providers.fraud import FraudProvider
from app.repositories.fraud_assessment import FraudAssessmentRepository


class FraudAssessmentService:
    def __init__(
        self,
        repository: FraudAssessmentRepository,
        provider: FraudProvider,
    ):
        self.repository = repository
        self.provider = provider

    async def assess(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
    ):
        existing = await self.repository.list_by_loan_application(
            application_id
        )

        for assessment in reversed(existing):
            if assessment.status == FraudAssessmentStatus.COMPLETED:
                return assessment

        requested_at = datetime.now(timezone.utc)

        try:
            result = await self.provider.assess_fraud(
                user_id=user_id,
                application_id=application_id,
            )
        except asyncio.TimeoutError:
            result = FraudAssessmentResult(
                provider="unknown",
                provider_reference=f"timeout-{application_id}-{uuid4().hex}",
                status=FraudAssessmentStatus.FAILED,
                risk_level=FraudRiskLevel.UNKNOWN,
                failure_reason="fraud provider timeout",
            )

        received_at = datetime.now(timezone.utc)

        signals = [
            {
                "code": signal.code,
                "description": signal.description,
                "severity": signal.severity,
            }
            for signal in result.signals
        ]

        return await self.repository.create(
            loan_application_id=application_id,
            user_id=user_id,
            provider=result.provider,
            provider_reference=result.provider_reference,
            status=result.status,
            risk_level=result.risk_level,
            signals=signals,
            model_version=None,
            requested_at=requested_at,
            received_at=received_at,
            failure_reason=result.failure_reason,
        )