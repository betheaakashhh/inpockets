from __future__ import annotations

from uuid import UUID

from app.domain.admin import AdminPermission
from app.repositories.audit_log import AuditLogRepository
from app.repositories.admin_user import AdminUserRepository
from app.services.audit_log import AuditLogService
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
        audit_log_service: AuditLogService,
    ):
        self.review_case_repository = review_case_repository
        self.admin_authorization_service = admin_authorization_service
        self.audit_log_service = audit_log_service

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

        result = await self.review_case_repository.assign(
            case_id=case_id,
            admin_user_id=assignee_admin_user_id,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_CASE_ASSIGNED",
            entity_type="underwriting_review_case",
            entity_id=str(case_id),
            old_value={
                "assigned_admin_user_id": (
                    str(case.assigned_admin_user_id)
                    if case.assigned_admin_user_id
                    else None
                ),
                "status": case.status.value,
            },
            new_value={
                "assigned_admin_user_id": str(assignee_admin_user_id),
                "status": result.status.value,
            },
        )

        return result

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

        result = await self.review_case_repository.start_review(
            case_id=case_id,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_REVIEW_STARTED",
            entity_type="underwriting_review_case",
            entity_id=str(case_id),
            old_value={
                "status": case.status.value,
            },
            new_value={
                "status": result.status.value,
            },
        )

        return result

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

        result = await self.review_case_repository.complete(
            case_id=case_id,
            status="APPROVED",
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_CASE_APPROVED",
            entity_type="underwriting_review_case",
            entity_id=str(case_id),
            old_value={
                "status": case.status.value,
            },
            new_value={
                "status": result.status.value,
            },
        )

        return result

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

        result = await self.review_case_repository.complete(
            case_id=case_id,
            status="REJECTED",
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_CASE_REJECTED",
            entity_type="underwriting_review_case",
            entity_id=str(case_id),
            old_value={
                "status": case.status.value,
            },
            new_value={
                "status": result.status.value,
            },
        )

        return result

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

        result = await self.review_case_repository.complete(
            case_id=case_id,
            status="CLOSED",
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_CASE_CLOSED",
            entity_type="underwriting_review_case",
            entity_id=str(case_id),
            old_value={
                "status": case.status.value,
            },
            new_value={
                "status": result.status.value,
            },
        )

        return result

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

        result = await self.review_case_repository.assign(
            case_id=case_id,
            admin_user_id=actor_admin.id,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_CASE_CLAIMED",
            entity_type="underwriting_review_case",
            entity_id=str(case_id),
            old_value={
                "assigned_admin_user_id": None,
                "status": case.status.value,
            },
            new_value={
                "assigned_admin_user_id": str(actor_admin.id),
                "status": result.status.value,
            },
        )

        return result

    @staticmethod
    def _require_reviewable_case(case) -> None:
        if case.status != "IN_REVIEW":
            raise ValueError(
                "underwriting review case must be IN_REVIEW before a decision"
            )
    