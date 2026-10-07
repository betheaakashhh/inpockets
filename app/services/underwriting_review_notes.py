from __future__ import annotations

from uuid import UUID

from app.domain.admin import AdminPermission
from app.models.underwriting_review_evidence import (
    UnderwritingReviewEvidence,
)
from app.models.underwriting_review_note import (
    UnderwritingReviewNote,
)
from app.repositories.admin_user import AdminUserRepository
from app.repositories.underwriting_review_case import (
    UnderwritingReviewCaseRepository,
)
from app.repositories.underwriting_review_evidence import (
    UnderwritingReviewEvidenceRepository,
)
from app.repositories.underwriting_review_note import (
    UnderwritingReviewNoteRepository,
)
from app.services.admin_authorization import (
    AdminAuthorizationService,
)
from app.repositories.audit_log import AuditLogRepository
from app.services.audit_log import AuditLogService

class UnderwritingReviewNotesService:
    """Authorized access to underwriting review notes and evidence."""

    def __init__(self, *, session, audit_log_service: AuditLogService | None = None):
        self.admin_user_repository = AdminUserRepository(session)
        self.authorization = AdminAuthorizationService(
            admin_user_repository=self.admin_user_repository,
        )
        self.case_repository = UnderwritingReviewCaseRepository(session)
        self.note_repository = UnderwritingReviewNoteRepository(session)
        self.evidence_repository = UnderwritingReviewEvidenceRepository(session)
        self.audit_log_service = audit_log_service or AuditLogService(
            audit_log_repository=AuditLogRepository(session),
            admin_user_repository=self.admin_user_repository,
        )

    async def _require_admin(
        self,
        *,
        actor_user_id: UUID,
    ):
        await self.authorization.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.UNDERWRITING_REVIEW,
        )

        admin_user = await self.admin_user_repository.get_by_user_id(
            actor_user_id,
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

    async def add_note(
        self,
        *,
        actor_user_id: UUID,
        review_case_id: UUID,
        content: str,
        
    ) -> UnderwritingReviewNote:
        admin_user = await self._require_admin(
            actor_user_id=actor_user_id,
            
            
        )

        await self._require_case(
            review_case_id=review_case_id,
        )

        content = content.strip()

        if not content:
            raise ValueError("review note content is required")

        note = await self.note_repository.create(
            review_case_id=review_case_id,
            author_admin_user_id=admin_user.id,
            content=content,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_REVIEW_NOTE_ADDED",
            entity_type="underwriting_review_note",
            entity_id=str(note.id),
            old_value=None,
            new_value=None,
            event_metadata={"review_case_id": str(review_case_id)},
        )

        return note

    async def list_notes(
        self,
        *,
        actor_user_id: UUID,
        review_case_id: UUID,
    ) -> list[UnderwritingReviewNote]:
        await self._require_admin(
            actor_user_id=actor_user_id,
        )

        await self._require_case(
            review_case_id=review_case_id,
        )

        return await self.note_repository.list_by_review_case(
            review_case_id=review_case_id,
        )

    async def add_evidence(
        self,
        *,
        actor_user_id: UUID,
        review_case_id: UUID,
        evidence_type: str,
        reference: str,
        evidence_metadata: dict[str, object],
    ) -> UnderwritingReviewEvidence:
        admin_user = await self._require_admin(
            actor_user_id=actor_user_id,
        )

        await self._require_case(
            review_case_id=review_case_id,
        )

        evidence_type = evidence_type.strip()
        reference = reference.strip()

        if not evidence_type:
            raise ValueError("evidence type is required")

        if not reference:
            raise ValueError("evidence reference is required")

        if evidence_metadata is None:
            raise ValueError("evidence metadata is required")

        evidence = await self.evidence_repository.create(
            review_case_id=review_case_id,
            added_by_admin_user_id=admin_user.id,
            evidence_type=evidence_type,
            reference=reference,
            evidence_metadata=evidence_metadata,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="UNDERWRITING_REVIEW_EVIDENCE_ADDED",
            entity_type="underwriting_review_evidence",
            entity_id=str(evidence.id),
            old_value=None,
            new_value=None,
            event_metadata={"review_case_id": str(review_case_id)},
        )

        return evidence

    async def list_evidence(
        self,
        *,
        actor_user_id: UUID,
        review_case_id: UUID,
    ) -> list[UnderwritingReviewEvidence]:
        await self._require_admin(
            actor_user_id=actor_user_id,
        )

        await self._require_case(
            review_case_id=review_case_id,
        )

        return await self.evidence_repository.list_by_review_case(
            review_case_id=review_case_id,
        )