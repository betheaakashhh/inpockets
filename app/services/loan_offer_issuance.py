from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.core.config import Settings, get_settings
from app.domain.admin import AdminPermission
from app.domain.loan_application import LoanApplicationStatus
from app.domain.loan_offer import (
    LoanOfferConflict,
    LoanOfferNotFound,
    LoanOfferStatus,
)
from app.models.loan_offer import LoanOffer
from app.repositories.loan_application import LoanApplicationRepository
from app.repositories.loan_offer import LoanOfferRepository
from app.services.document import DocumentService
from app.services.loan_offer import LoanOfferService
from app.services.loan_offer_pdf import LoanOfferPDFGenerator
from app.services.offer_templates import (
    AGREEMENT_TEMPLATE_KEY,
    KFS_TEMPLATE_KEY,
    OfferTemplateRegistry,
    build_registry,
    require_issuable,
)


class LoanOfferIssuanceService:
    """Generates the KFS + agreement for a draft offer and issues it.

    Runs inside the caller's transaction: if any step fails, the offer stays
    DRAFT. Generated PDFs are deterministic, so a retry after a failure
    resolves to the same stored documents instead of creating new ones.
    """

    def __init__(
        self,
        *,
        offer_service: LoanOfferService,
        document_service: DocumentService,
        offer_repository: LoanOfferRepository,
        application_repository: LoanApplicationRepository,
        pdf_generator: type[LoanOfferPDFGenerator] = LoanOfferPDFGenerator,
        settings: Settings | None = None,
        template_registry: OfferTemplateRegistry | None = None,
    ):
        self.offer_service = offer_service
        self.document_service = document_service
        self.offer_repository = offer_repository
        self.application_repository = application_repository
        self.pdf_generator = pdf_generator
        self.settings = settings or get_settings()
        self.template_registry = template_registry or build_registry(self.settings)

    async def issue(
        self,
        *,
        actor_user_id: UUID,
        offer_id: UUID,
        validity: timedelta | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoanOffer:
        # Authorize before doing any expensive generation or storage writes.
        await self.offer_service.admin_authorization_service.require_permission(
            user_id=actor_user_id,
            permission=AdminPermission.LOAN_OFFER_ISSUE,
        )

        kfs_template = self.template_registry.get(
            KFS_TEMPLATE_KEY,
            getattr(self.settings, "loan_offer_kfs_template_version", "draft-v1"),
        )
        agreement_template = self.template_registry.get(
            AGREEMENT_TEMPLATE_KEY,
            getattr(
                self.settings, "loan_offer_agreement_template_version", "draft-v1"
            ),
        )
        for template in (kfs_template, agreement_template):
            require_issuable(template, settings=self.settings)
        lender_name = getattr(self.settings, "lender_name", None)

        validity = validity or timedelta(
            hours=self.settings.loan_offer_validity_hours
        )

        # Same lock order as LoanOfferService.issue_offer: application, offer.
        preliminary = await self.offer_repository.get_by_id(offer_id=offer_id)
        if preliminary is None:
            raise LoanOfferNotFound("Loan offer not found.")

        application = await self.application_repository.get_by_id_for_update(
            application_id=preliminary.loan_application_id,
        )
        if application is None:
            raise LoanOfferNotFound("Loan application not found.")

        offer = await self.offer_repository.get_by_id_for_update(
            offer_id=offer_id,
        )
        if offer is None:
            raise LoanOfferNotFound("Loan offer not found.")
        if offer.status != LoanOfferStatus.DRAFT.value:
            raise LoanOfferConflict("Only draft offers can be issued.")
        if application.status != LoanApplicationStatus.APPROVED.value:
            raise LoanOfferConflict(
                "A loan offer can only be issued for an approved application."
            )

        kfs_bytes = self.pdf_generator.generate_kfs(
            offer=offer, template=kfs_template, lender_name=lender_name
        )
        agreement_bytes = self.pdf_generator.generate_agreement(
            offer=offer, template=agreement_template, lender_name=lender_name
        )

        kfs = await self._store(
            offer=offer,
            owner_id=application.user_id,
            document_type="KFS",
            template=kfs_template,
            content=kfs_bytes,
        )
        agreement = await self._store(
            offer=offer,
            owner_id=application.user_id,
            document_type="LOAN_AGREEMENT",
            template=agreement_template,
            content=agreement_bytes,
        )

        return await self.offer_service.issue_offer(
            actor_user_id=actor_user_id,
            offer_id=offer.id,
            kfs_document_id=kfs.id,
            agreement_document_id=agreement.id,
            expires_in=validity,
            request_id=request_id,
            ip_address=ip_address,
        )

    async def _store(
        self,
        *,
        offer: LoanOffer,
        owner_id: UUID,
        document_type: str,
        template,
        content: bytes,
    ):
        return await self.document_service.store_document(
            owner_type="USER",
            owner_id=owner_id,
            document_type=document_type,
            content=content,
            content_type="application/pdf",
            key_hint=f"{template.key}-v{offer.version}",
            immutable=True,
            loan_offer_id=offer.id,
            loan_offer_version=offer.version,
            template_key=template.key,
            template_version=template.version,
        )
