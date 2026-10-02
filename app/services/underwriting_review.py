from __future__ import annotations

from uuid import UUID

from app.domain.admin import AdminPermission
from app.repositories.admin_user import AdminUserRepository
from app.repositories.underwriting_review_case import (
    UnderwritingReviewCaseRepository,
)
from app.services.admin_authorization import AdminAuthorizationService


class UnderwritingReviewService:
    """Application service for lender-admin underwriting review."""

    def __init__(
        self,
        *,
        review_case_repository: UnderwritingReviewCaseRepository,
        admin_authorization_service: AdminAuthorizationService,
    ):
        self.review_case_repository = review_case_repository
        self.admin_authorization_service = admin_authorization_service

    async def assign_case(
        self,
        *,
        actor_user_id: UUID,
        case_id: UUID,
        assignee_admin_user_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_ASSIGN,
        )

        case = await self.review_case_repository.get_by_id(case_id)

        if case is None:
            raise ValueError("underwriting review case not found")

        if not case.is_open:
            raise ValueError("underwriting review case is already closed")

        return await self.review_case_repository.assign(
            case_id=case_id,
            admin_user_id=assignee_admin_user_id,
        )

    async def start_review(
        self,
        *,
        actor_user_id: UUID,
        case_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_REVIEW,
        )

        case = await self.review_case_repository.get_by_id(case_id)

        if case is None:
            raise ValueError("underwriting review case not found")

        if case.status not in {"ASSIGNED", "IN_REVIEW"}:
            raise ValueError(
                "underwriting review case must be assigned before review"
            )

        admin_user_repository = (
            self.admin_authorization_service.admin_user_repository
        )
        actor_admin = await admin_user_repository.get_by_user_id(actor_user_id)

        if actor_admin is None:
            raise PermissionError("user is not an admin")

        if (
            case.assigned_admin_user_id is not None
            and case.assigned_admin_user_id != actor_admin.id
        ):
            raise PermissionError(
                "underwriting review case is assigned to another admin"
            )

        return await self.review_case_repository.start_review(
            case_id=case_id,
        )

    async def approve_case(
        self,
        *,
        actor_user_id: UUID,
        case_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_APPROVE,
        )

        case = await self.review_case_repository.get_by_id(case_id)

        if case is None:
            raise ValueError("underwriting review case not found")

        self._require_reviewable_case(case)

        return await self.review_case_repository.complete(
            case_id=case_id,
            status="APPROVED",
        )

    async def reject_case(
        self,
        *,
        actor_user_id: UUID,
        case_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_REJECT,
        )

        case = await self.review_case_repository.get_by_id(case_id)

        if case is None:
            raise ValueError("underwriting review case not found")

        self._require_reviewable_case(case)

        return await self.review_case_repository.complete(
            case_id=case_id,
            status="REJECTED",
        )

    async def close_case(
        self,
        *,
        actor_user_id: UUID,
        case_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_REVIEW,
        )

        case = await self.review_case_repository.get_by_id(case_id)

        if case is None:
            raise ValueError("underwriting review case not found")

        if not case.is_open:
            raise ValueError("underwriting review case is already closed")

        return await self.review_case_repository.complete(
            case_id=case_id,
            status="CLOSED",
        )
    
    async def list_queue(
        self,
        *,
        actor_user_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_REVIEW,
        )

        return await self.review_case_repository.list_by_status(
            status="QUEUED",
        )


    async def list_my_cases(
        self,
        *,
        actor_user_id: UUID,
        status: str | None = None,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_REVIEW,
    )

        actor_admin = (
            await self.admin_authorization_service.admin_user_repository
            .get_by_user_id(actor_user_id)
        )

        if actor_admin is None:
            raise PermissionError("user is not an admin")

        return await self.review_case_repository.list_by_assigned_admin(
            admin_user_id=actor_admin.id,
            status=status,
        )


    async def claim_case(
        self,
        *,
        actor_user_id: UUID,
        case_id: UUID,
    ):
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_ASSIGN,
        )

        actor_admin = (
            await self.admin_authorization_service.admin_user_repository
            .get_by_user_id(actor_user_id)
        )

        if actor_admin is None:
            raise PermissionError("user is not an admin")

        case = await self.review_case_repository.get_by_id(case_id)

        if case is None:
            raise ValueError("underwriting review case not found")

        if case.status != "QUEUED":
            raise ValueError(
                "only QUEUED underwriting review cases can be claimed"
            )

        return await self.review_case_repository.assign(
            case_id=case_id,
            admin_user_id=actor_admin.id,
        )

    @staticmethod
    def _require_reviewable_case(case) -> None:
        if case.status != "IN_REVIEW":
            raise ValueError(
                "underwriting review case must be IN_REVIEW before a decision"
            )
    