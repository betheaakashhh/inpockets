from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin import AdminPermission
from app.domain.loan_application import LoanApplicationStatus
import app.domain.loan_offer as offer_domain
from app.domain.loan_offer import (
    LoanOfferConflict,
    LoanOfferNotFound,
    LoanOfferStatus,
    LoanOfferTerms,
)
from app.models.document import Document
from app.models.loan_offer import LoanOffer
from app.repositories.admin_user import AdminUserRepository
from app.repositories.document import DocumentRepository
from app.repositories.loan_application import LoanApplicationRepository
from app.repositories.loan_decision import LoanDecisionRepository
from app.repositories.loan_offer import LoanOfferRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService


class LoanOfferService:
    """Enforces offer lifecycle, ownership, authorization, and immutability."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        offer_repository: LoanOfferRepository,
        application_repository: LoanApplicationRepository,
        document_repository: DocumentRepository,
        admin_authorization_service: AdminAuthorizationService,
        audit_log_service: AuditLogService,
        decision_repository: LoanDecisionRepository | None = None,
    ):
        self.session = session
        self.offer_repository = offer_repository
        self.application_repository = application_repository
        self.document_repository = document_repository
        self.admin_authorization_service = admin_authorization_service
        self.audit_log_service = audit_log_service
        self.decision_repository = decision_repository
        self.admin_user_repository = AdminUserRepository(session)

    # ------------------------------------------------------------------
    # Admin: create / issue / cancel / read
    # ------------------------------------------------------------------

    async def create_draft(
        self,
        *,
        actor_user_id: UUID,
        loan_application_id: UUID,
        principal_amount: Decimal,
        tenure_days: int,
        commercial_terms: dict,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoanOffer:
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_APPLICATION_REVIEW,
        )

        application = await self.application_repository.get_by_id_for_update(
            application_id=loan_application_id,
        )
        if application is None:
            raise LoanOfferNotFound("Loan application not found.")

        if application.status != LoanApplicationStatus.APPROVED.value:
            raise LoanOfferConflict(
                "A loan offer can only be created for an approved application."
            )

        terms = LoanOfferTerms(
            principal_amount=principal_amount,
            tenure_days=tenure_days,
            commercial_terms=commercial_terms,
        )

        await self._enforce_amount_limits(
            application=application,
            principal_amount=terms.principal_amount,
        )

        accepted = await self.offer_repository.get_accepted_for_application(
            loan_application_id=loan_application_id,
        )
        if accepted is not None:
            raise LoanOfferConflict(
                "An offer has already been accepted for this application."
            )

        latest = (
            await self.offer_repository.get_latest_for_application_for_update(
                loan_application_id=loan_application_id,
            )
        )
        version = 1 if latest is None else latest.version + 1

        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        if admin is None or not admin.is_active:
            raise PermissionError("Active lender admin required.")

        offer = await self.offer_repository.create(
            loan_application_id=application.id,
            user_id=application.user_id,
            version=version,
            principal_amount=terms.principal_amount,
            tenure_days=terms.tenure_days,
            commercial_terms=terms.commercial_terms,
            created_by_admin_user_id=admin.id,
        )

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="LOAN_OFFER_DRAFT_CREATED",
            entity_type="loan_offer",
            entity_id=str(offer.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value={
                "loan_application_id": str(application.id),
                "version": offer.version,
                "principal_amount": str(offer.principal_amount),
                "tenure_days": offer.tenure_days,
            },
        )
        return offer

    async def issue_offer(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
        kfs_document_id: UUID,
        agreement_document_id: UUID,
        expires_in: timedelta = timedelta(days=7),
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoanOffer:
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_OFFER_ISSUE,
        )

        if expires_in <= timedelta(0):
            raise ValueError("Offer expiry duration must be positive.")

        # Preliminary lookup only: discover the application to lock first.
        # Lock order is always application -> offer to avoid deadlocks.
        preliminary_offer = await self.offer_repository.get_by_id(
            offer_id=offer_id,
        )
        if preliminary_offer is None:
            raise LoanOfferNotFound("Loan offer not found.")

        application = await self.application_repository.get_by_id_for_update(
            application_id=preliminary_offer.loan_application_id,
        )
        if application is None:
            raise LoanOfferNotFound("Loan application not found.")

        # Re-read the offer under lock and revalidate its relationship.
        offer = await self.offer_repository.get_by_id_for_update(
            offer_id=offer_id,
        )
        if offer is None:
            raise LoanOfferNotFound("Loan offer not found.")
        if offer.loan_application_id != application.id:
            raise LoanOfferConflict("Loan offer application changed unexpectedly.")
        if offer.status != LoanOfferStatus.DRAFT.value:
            raise LoanOfferConflict("Only draft offers can be issued.")
        if application.status != LoanApplicationStatus.APPROVED.value:
            raise LoanOfferConflict(
                "A loan offer can only be issued for an approved application."
            )

        kfs = await self._require_immutable_document(
            document_id=kfs_document_id,
            expected_type="KFS",
            expected_owner_id=application.user_id,
            expected_offer_id=offer.id,
            expected_offer_version=offer.version,
        )

        agreement = await self._require_immutable_document(
            document_id=agreement_document_id,
            expected_type="LOAN_AGREEMENT",
            expected_owner_id=application.user_id,
            expected_offer_id=offer.id,
            expected_offer_version=offer.version,
        )
        if kfs.id == agreement.id:
            raise ValueError("KFS and agreement must be separate documents.")

        await self._supersede_open_offers(
            actor_user_id=actor_user_id,
            application_id=application.id,
            new_offer=offer,
            request_id=request_id,
            ip_address=ip_address,
        )

        now = self._utcnow()
        offer.kfs_document_id = kfs.id
        offer.agreement_document_id = agreement.id
        offer.issued_at = now
        offer.expires_at = now + expires_in
        offer.status = LoanOfferStatus.ISSUED.value

        await self.offer_repository.update(offer)

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="LOAN_OFFER_ISSUED",
            entity_type="loan_offer",
            entity_id=str(offer.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"status": LoanOfferStatus.DRAFT.value},
            new_value={
                "status": offer.status,
                "version": offer.version,
                "kfs_document_id": str(kfs.id),
                "agreement_document_id": str(agreement.id),
                "expires_at": offer.expires_at.isoformat(),
            },
        )
        return offer

    async def cancel_offer(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
        reason: str,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoanOffer:
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_OFFER_CANCEL,
        )

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("Offer cancellation reason is required.")

        offer = await self.offer_repository.get_by_id_for_update(
            offer_id=offer_id,
        )
        if offer is None:
            raise LoanOfferNotFound("Loan offer not found.")
        if offer.status != LoanOfferStatus.ISSUED.value:
            raise LoanOfferConflict("Only issued offers can be cancelled.")

        offer.status = LoanOfferStatus.CANCELLED.value
        await self.offer_repository.update(offer)

        await self.audit_log_service.record_admin_action(
            actor_user_id=actor_user_id,
            action="LOAN_OFFER_CANCELLED",
            entity_type="loan_offer",
            entity_id=str(offer.id),
            request_id=request_id,
            ip_address=ip_address,
            reason=normalized_reason,
            old_value={"status": LoanOfferStatus.ISSUED.value},
            new_value={
                "status": offer.status,
                "reason": normalized_reason,
            },
        )
        return offer

    async def get_for_admin(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
    ) -> LoanOffer:
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_APPLICATION_READ,
        )
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if offer is None:
            raise LoanOfferNotFound("Loan offer not found.")
        return offer

    async def list_for_application_admin(
        self,
        *,
        actor_user_id: UUID,
        loan_application_id: UUID,
    ) -> list[LoanOffer]:
        await self.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_APPLICATION_READ,
        )
        return await self.offer_repository.list_by_application_id(
            loan_application_id=loan_application_id,
        )

    # ------------------------------------------------------------------
    # Customer: list / read / accept / decline
    # ------------------------------------------------------------------

    async def list_for_customer(self, *, actor_user_id: UUID) -> list[LoanOffer]:
        offers = await self.offer_repository.list_by_user_id(
            user_id=actor_user_id,
        )
        # Drafts are internal working copies and are never shown to customers.
        return [o for o in offers if o.status != LoanOfferStatus.DRAFT.value]

    async def get_for_customer(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
    ) -> LoanOffer:
        offer = await self.offer_repository.get_by_id(offer_id=offer_id)
        if (
            offer is None
            or offer.user_id != actor_user_id
            or offer.status == LoanOfferStatus.DRAFT.value
        ):
            raise LoanOfferNotFound("Loan offer not found.")
        return offer

    async def record_document_view(
        self,
        *,
        actor_user_id: UUID,
        offer: LoanOffer,
        document_kind: str,
        document_id: UUID,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Evidence that the customer was shown the KFS / agreement."""
        await self.audit_log_service.record_customer_action(
            actor_user_id=actor_user_id,
            action="LOAN_OFFER_DOCUMENT_VIEWED",
            entity_type="loan_offer",
            entity_id=str(offer.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value={
                "document_kind": document_kind,
                "document_id": str(document_id),
                "offer_version": offer.version,
            },
        )

    async def accept_offer(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
        expected_version: int | None = None,
        kfs_document_id: UUID | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoanOffer:
        """Record customer acceptance.

        Idempotent: re-accepting an already accepted offer returns it
        unchanged. An offer past expiry is persisted as EXPIRED and returned
        (it is never accepted); callers must check the returned status.
        """
        offer = await self.offer_repository.get_by_id_for_update(
            offer_id=offer_id,
        )
        if offer is None or offer.user_id != actor_user_id:
            raise LoanOfferNotFound("Loan offer not found.")

        if offer.status == LoanOfferStatus.ACCEPTED.value:
            self._require_acceptance_matches(
                offer, expected_version, kfs_document_id
            )
            return offer

        if offer.status == LoanOfferStatus.DRAFT.value:
            raise LoanOfferNotFound("Loan offer not found.")

        if offer.status != LoanOfferStatus.ISSUED.value:
            raise LoanOfferConflict("Only issued offers can be accepted.")

        now = self._utcnow()
        if offer.expires_at is None or now >= offer.expires_at:
            offer.status = LoanOfferStatus.EXPIRED.value
            await self.offer_repository.update(offer)
            await self.audit_log_service.record_customer_action(
                actor_user_id=actor_user_id,
                action="LOAN_OFFER_EXPIRED",
                entity_type="loan_offer",
                entity_id=str(offer.id),
                request_id=request_id,
                ip_address=ip_address,
                old_value={"status": LoanOfferStatus.ISSUED.value},
                new_value={"status": offer.status},
                event_metadata={"trigger": "acceptance_attempt_after_expiry"},
            )
            return offer

        self._require_acceptance_matches(
            offer, expected_version, kfs_document_id
        )

        if offer.kfs_document_id is None or offer.agreement_document_id is None:
            raise LoanOfferConflict("Offer documents are not available.")

        offer.status = LoanOfferStatus.ACCEPTED.value
        offer.accepted_at = now
        await self.offer_repository.update(offer)

        await self.audit_log_service.record_customer_action(
            actor_user_id=actor_user_id,
            action="LOAN_OFFER_ACCEPTED",
            entity_type="loan_offer",
            entity_id=str(offer.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"status": LoanOfferStatus.ISSUED.value},
            new_value={
                "status": offer.status,
                "version": offer.version,
                "principal_amount": str(offer.principal_amount),
                "tenure_days": offer.tenure_days,
                "kfs_document_id": str(offer.kfs_document_id),
                "agreement_document_id": str(offer.agreement_document_id),
                "accepted_at": now.isoformat(),
            },
        )
        return offer

    async def decline_offer(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoanOffer:
        offer = await self.offer_repository.get_by_id_for_update(
            offer_id=offer_id,
        )
        if offer is None or offer.user_id != actor_user_id:
            raise LoanOfferNotFound("Loan offer not found.")
        if offer.status == LoanOfferStatus.DRAFT.value:
            raise LoanOfferNotFound("Loan offer not found.")
        if offer.status == LoanOfferStatus.DECLINED.value:
            return offer  # idempotent retry
        if offer.status != LoanOfferStatus.ISSUED.value:
            raise LoanOfferConflict("Only issued offers can be declined.")

        now = self._utcnow()
        if offer.expires_at is None or now >= offer.expires_at:
            offer.status = LoanOfferStatus.EXPIRED.value
        else:
            offer.status = LoanOfferStatus.DECLINED.value

        await self.offer_repository.update(offer)

        await self.audit_log_service.record_customer_action(
            actor_user_id=actor_user_id,
            action=(
                "LOAN_OFFER_DECLINED"
                if offer.status == LoanOfferStatus.DECLINED.value
                else "LOAN_OFFER_EXPIRED"
            ),
            entity_type="loan_offer",
            entity_id=str(offer.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value={"status": LoanOfferStatus.ISSUED.value},
            new_value={"status": offer.status},
        )
        return offer

    # ------------------------------------------------------------------
    # System: expiry
    # ------------------------------------------------------------------

    async def expire_offer(
        self,
        *,
        offer_id: UUID,
    ) -> LoanOffer:
        offer = await self.offer_repository.get_by_id_for_update(
            offer_id=offer_id,
        )
        if offer is None:
            raise LoanOfferNotFound("Loan offer not found.")
        if offer.status != LoanOfferStatus.ISSUED.value:
            raise LoanOfferConflict("Only issued offers can expire.")
        if offer.expires_at is None or self._utcnow() < offer.expires_at:
            raise LoanOfferConflict("Loan offer has not expired.")

        offer.status = LoanOfferStatus.EXPIRED.value
        await self.offer_repository.update(offer)
        return offer

    async def expire_due_offers(self, *, batch_size: int = 100) -> int:
        """Bounded, retry-safe sweep for the expiry worker.

        Rows are claimed with SKIP LOCKED, so concurrent workers never
        process the same offer, and a re-run simply finds nothing to do.
        The caller owns the transaction (commit after this returns).
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")

        due = await self.offer_repository.list_due_for_expiry_for_update(
            now=self._utcnow(),
            limit=batch_size,
        )
        for offer in due:
            offer.status = LoanOfferStatus.EXPIRED.value
            await self.offer_repository.update(offer)
            await self.audit_log_service.record_system_action(
                action="LOAN_OFFER_EXPIRED",
                entity_type="loan_offer",
                entity_id=str(offer.id),
                old_value={"status": LoanOfferStatus.ISSUED.value},
                new_value={"status": offer.status},
                event_metadata={"trigger": "expiry_sweep"},
            )
        return len(due)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _enforce_amount_limits(
        self,
        *,
        application,
        principal_amount: Decimal,
    ) -> None:
        """An offer may never exceed what was asked for or what policy allows."""
        requested = application.requested_amount
        if requested is not None and principal_amount > requested:
            raise ValueError(
                "Offer principal cannot exceed the requested amount."
            )

        if self.decision_repository is None:
            return

        decision = await self.decision_repository.get_latest_for_loan_application(
            application.id
        )
        if (
            decision is not None
            and decision.max_eligible_amount is not None
            and principal_amount > decision.max_eligible_amount
        ):
            raise ValueError(
                "Offer principal cannot exceed the maximum eligible amount "
                "from the policy decision."
            )

    async def _supersede_open_offers(
        self,
        *,
        actor_user_id: UUID,
        application_id: UUID,
        new_offer: LoanOffer,
        request_id: str | None,
        ip_address: str | None,
    ) -> None:
        open_offers = (
            await self.offer_repository.list_open_for_application_for_update(
                loan_application_id=application_id,
            )
        )
        for previous in open_offers:
            if previous.id == new_offer.id:
                continue

            if previous.status == LoanOfferStatus.ACCEPTED.value:
                raise LoanOfferConflict(
                    "An offer has already been accepted for this application."
                )

            previous.status = LoanOfferStatus.CANCELLED.value
            # Flush now: the partial unique index allows one open offer per
            # application, so the old one must leave ISSUED first.
            await self.offer_repository.update(previous)
            await self.audit_log_service.record_admin_action(
                actor_user_id=actor_user_id,
                action="LOAN_OFFER_SUPERSEDED",
                entity_type="loan_offer",
                entity_id=str(previous.id),
                request_id=request_id,
                ip_address=ip_address,
                reason=f"Superseded by offer version {new_offer.version}",
                old_value={"status": LoanOfferStatus.ISSUED.value},
                new_value={
                    "status": previous.status,
                    "superseded_by_offer_id": str(new_offer.id),
                },
            )

    @staticmethod
    def _require_acceptance_matches(
        offer: LoanOffer,
        expected_version: int | None,
        kfs_document_id: UUID | None,
    ) -> None:
        """The customer must accept exactly the terms/KFS they were shown."""
        if expected_version is not None and expected_version != offer.version:
            raise LoanOfferConflict(
                "The offer has changed. Please review the latest offer."
            )
        if (
            kfs_document_id is not None
            and kfs_document_id != offer.kfs_document_id
        ):
            raise LoanOfferConflict(
                "The Key Facts Statement has changed. "
                "Please review the latest offer."
            )

    async def _require_immutable_document(
        self,
        *,
        document_id: UUID,
        expected_type: str,
        expected_owner_id: UUID,
        expected_offer_id: UUID,
        expected_offer_version: int,
    ) -> Document:
        document = await self.document_repository.get_by_id(document_id)

        if document is None:
            raise ValueError(f"Required {expected_type} document not found.")

        if (
            document.owner_type != "USER"
            or document.owner_id != expected_owner_id
        ):
            raise ValueError(
                f"{expected_type} document does not belong to the applicant."
            )

        if document.document_type != expected_type:
            raise ValueError(f"Document must have type {expected_type}.")

        if not document.is_immutable:
            raise ValueError(f"{expected_type} document must be immutable.")

        if document.content_type != "application/pdf":
            raise ValueError(f"{expected_type} document must be a PDF.")

        if document.loan_offer_id != expected_offer_id:
            raise ValueError(
                f"{expected_type} document belongs to a different loan offer."
            )

        if document.loan_offer_version != expected_offer_version:
            raise ValueError(
                f"{expected_type} document has an incorrect loan offer version."
            )

        if (
            not isinstance(document.template_key, str)
            or not document.template_key.strip()
        ):
            raise ValueError(
                f"{expected_type} document must have a template key."
            )

        if (
            not isinstance(document.template_version, str)
            or not document.template_version.strip()
        ):
            raise ValueError(
                f"{expected_type} document must have a template version."
            )

        return document

    @staticmethod
    def _utcnow() -> datetime:
        return offer_domain.utcnow()
