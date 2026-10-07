from __future__ import annotations

from uuid import UUID

from app.domain.admin import AdminPermission
from app.models.underwriting_override import UnderwritingOverride
from app.repositories.admin_user import AdminUserRepository
from app.repositories.underwriting_override import UnderwritingOverrideRepository
from app.repositories.underwriting_review_case import UnderwritingReviewCaseRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService


class UnderwritingOverrideService:
    """Authorized service for controlled underwriting overrides."""

    def __init__(
        self,
        *,
        session,
        audit_log_service: AuditLogService,
    ):
        self.admin_user_repository = AdminUserRepository(session)

        self.authorization = AdminAuthorizationService(
            admin_user_repository=self.admin_user_repository,
        )

        self.case_repository = UnderwritingReviewCaseRepository(session)
        self.override_repository = UnderwritingOverrideRepository(session)
        self.audit_log_service = audit_log_service

    async def _require_admin(
        self,
        *,
        actor_user_id: UUID,
        permission: AdminPermission,
    ):
        await self.authorization.require_permission(
            user_id=actor_user_id,
            permission=permission,
        )

        admin_user = await self.admin_user_repository.get_by_user_id(
            actor_user_id
        )

        if admin_user is None:
            raise PermissionError("user is not an admin")

        if not admin_user.is_active:
            raise PermissionError("admin user is inactive")

        return admin_user

    async def _require_case(
        self,
        *,
        review_case_id: UUID,
    ):
        case = await self.case_repository.get_by_id(
            case_id=review_case_id,
        )

        if case is None:
            raise ValueError("underwriting review case not found")

        return case

    async def request_override(
        self,
        *,
        actor_user_id: UUID,
        review_case_id: UUID,
        override_type: str,
        original_value: dict[str, object],
        requested_value: dict[str, object],
        reason: str,
    ) -> UnderwritingOverride:
        admin_user = await self._require_admin(
            actor_user_id=actor_user_id,
            permission=AdminPermission.LOAN_OVERRIDE,
        )

        case = await self._require_case(
            review_case_id=review_case_id,
        )

        if case.status in {"APPROVED", "REJECTED", "CLOSED"}:
            raise ValueError(
                "override can only be requested for an open review case"
            )

        override_type = override_type.strip()
        reason = reason.strip()

        if not override_type:
            raise ValueError("override_type is required")

        if not original_value:
            raise ValueError("original_value is required")

        if not requested_value:
            raise ValueError("requested_value is required")

        if not reason:
            raise ValueError("override reason is required")

        result = await self.override_repository.create(
            review_case_id=review_case_id,
            requested_by_admin_user_id=admin_user.id,
            override_type=override_type,
            original_value=original_value,
            requested_value=requested_value,
            reason=reason,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_OVERRIDE_REQUESTED",
            entity_type="underwriting_override",
            entity_id=str(result.id),
            reason=reason,
            old_value={
                "status": None,
            },
            new_value={
                "status": result.status,
            },
            event_metadata={
                "review_case_id": str(review_case_id),
                "override_type": override_type,
            },
        )

        return result

    async def approve_override(
        self,
        *,
        actor_user_id: UUID,
        override_id: UUID,
    ) -> UnderwritingOverride:
        admin_user = await self._require_admin(
            actor_user_id=actor_user_id,
            permission=AdminPermission.LOAN_OVERRIDE_APPROVE,
        )

        override = await self.override_repository.get_by_id(
            override_id=override_id,
        )

        if override is None:
            raise ValueError("underwriting override not found")

        if override.status != "REQUESTED":
            raise ValueError(
                "only requested overrides can be approved"
            )

        if override.requested_by_admin_user_id == admin_user.id:
            raise PermissionError(
                "override requester cannot approve their own override"
            )

        result = await self.override_repository.approve(
            override_id=override_id,
            approved_by_admin_user_id=admin_user.id,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_OVERRIDE_APPROVED",
            entity_type="underwriting_override",
            entity_id=str(result.id),
            reason=result.reason,
            old_value={
                "status": "REQUESTED",
            },
            new_value={
                "status": result.status,
            },
            event_metadata={
                "review_case_id": str(result.review_case_id),
            },
        )

        return result

    async def reject_override(
        self,
        *,
        actor_user_id: UUID,
        override_id: UUID,
    ) -> UnderwritingOverride:
        admin_user = await self._require_admin(
            actor_user_id=actor_user_id,
            permission=AdminPermission.LOAN_OVERRIDE_APPROVE,
        )

        override = await self.override_repository.get_by_id(
            override_id=override_id,
        )

        if override is None:
            raise ValueError("underwriting override not found")

        if override.status != "REQUESTED":
            raise ValueError(
                "only requested overrides can be rejected"
            )

        if override.requested_by_admin_user_id == admin_user.id:
            raise PermissionError(
                "override requester cannot reject their own override"
            )

        result = await self.override_repository.reject(
            override_id=override_id,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_OVERRIDE_REJECTED",
            entity_type="underwriting_override",
            entity_id=str(result.id),
            reason=result.reason,
            old_value={
                "status": "REQUESTED",
            },
            new_value={
                "status": result.status,
            },
            event_metadata={
                "review_case_id": str(result.review_case_id),
            },
        )

        return result