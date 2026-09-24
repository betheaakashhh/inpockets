from __future__ import annotations

import uuid
from decimal import Decimal

from app.domain.loan_application import (
    LoanApplicationStatus,
    is_valid_loan_application_transition,
)
from app.models.loan_application import LoanApplication
from app.repositories.loan_application import LoanApplicationRepository


class LoanApplicationService:
    def __init__(self, repository: LoanApplicationRepository):
        self.repository = repository

    async def create_draft(
        self,
        *,
        user_id: uuid.UUID,
        requested_amount: Decimal,
        requested_tenure_days: int,
    ) -> LoanApplication:
        if requested_amount <= Decimal("0"):
            raise ValueError("Requested amount must be greater than zero.")

        if requested_tenure_days <= 0:
            raise ValueError("Requested tenure must be greater than zero.")

        application_number = self._generate_application_number()

        application = await self.repository.create(
            application_number=application_number,
            user_id=user_id,
            status=LoanApplicationStatus.DRAFT,
            requested_amount=requested_amount,
            requested_tenure_days=requested_tenure_days,
        )

        await self.repository.create_event(
            application_id=application.id,
            event_type="APPLICATION_CREATED",
            previous_status=None,
            new_status=LoanApplicationStatus.DRAFT,
            actor_type="CUSTOMER",
            actor_id=user_id,
        )

        return application

    async def submit(
        self,
        *,
        application_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> LoanApplication:
        application = await self.repository.get_by_id_for_update(
            application_id=application_id,
        )

        if application is None:
            raise ValueError("Loan application not found.")

        if application.user_id != user_id:
            raise ValueError("Loan application does not belong to this user.")

        current_status = LoanApplicationStatus(application.status)

        # Idempotent behavior:
        # If submission has already happened, return the existing application.
        if current_status != LoanApplicationStatus.DRAFT:
            return application

        next_status = LoanApplicationStatus.SUBMITTED

        if not is_valid_loan_application_transition(
            current_status,
            next_status,
        ):
            raise ValueError(
                f"Invalid loan application transition: "
                f"{current_status} -> {next_status}"
            )

        application.status = next_status
        application.submitted_at = application.submitted_at or self._utcnow()

        await self.repository.update(application)

        await self.repository.create_event(
            application_id=application.id,
            event_type="APPLICATION_SUBMITTED",
            previous_status=current_status,
            new_status=next_status,
            actor_type="CUSTOMER",
            actor_id=user_id,
        )

        return application

    async def transition_status(
        self,
        *,
        application_id: uuid.UUID,
        next_status: LoanApplicationStatus,
        actor_type: str,
        actor_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> LoanApplication:
        application = await self.repository.get_by_id_for_update(
            application_id=application_id,
        )

        if application is None:
            raise ValueError("Loan application not found.")

        current_status = LoanApplicationStatus(application.status)

        if current_status == next_status:
            return application

        if not is_valid_loan_application_transition(
            current_status,
            next_status,
        ):
            raise ValueError(
                f"Invalid loan application transition: "
                f"{current_status} -> {next_status}"
            )

        application.status = next_status

        await self.repository.update(application)

        await self.repository.create_event(
            application_id=application.id,
            event_type="STATUS_CHANGED",
            previous_status=current_status,
            new_status=next_status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )

        return application

    async def get_application(
        self,
        *,
        application_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> LoanApplication:
        application = await self.repository.get_by_id(
            application_id=application_id,
        )

        if application is None:
            raise ValueError("Loan application not found.")

        if application.user_id != user_id:
            raise ValueError("Loan application does not belong to this user.")

        return application

    async def list_user_applications(
        self,
        *,
        user_id: uuid.UUID,
    ) -> list[LoanApplication]:
        return await self.repository.list_by_user_id(user_id=user_id)

    async def get_events(
        self,
        *,
        application_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        application = await self.get_application(
            application_id=application_id,
            user_id=user_id,
        )

        return await self.repository.list_events(
            application_id=application.id,
        )

    @staticmethod
    def _generate_application_number() -> str:
        return f"LA-{uuid.uuid4().hex[:20].upper()}"

    @staticmethod
    def _utcnow():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)