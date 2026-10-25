from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import app.domain.pricing as dom
from app.core.config import Settings
from app.domain.admin import AdminPermission
from app.domain.repayment import today_ist, utcnow
from app.models.pricing import LoanOfferPricing, PricingVersion
from app.repositories.admin_user import AdminUserRepository
from app.repositories.pricing import PricingRepository
from app.services.admin_authorization import AdminAuthorizationService
from app.services.audit_log import AuditLogService

ENTITY = "pricing_version"


@dataclass(frozen=True)
class PreparedPricing:
    version: PricingVersion
    terms: dom.PricingTerms
    late: dom.LateTerms
    quote: dom.Quote

    def display_terms(self) -> dict[str, str]:
        return dom.display_terms(
            version=self.version.version, terms=self.terms, late=self.late, qt=self.quote
        )


def terms_of(v) -> dom.PricingTerms:
    return dom.PricingTerms(
        annual_interest_percent=Decimal(v.annual_interest_percent),
        processing_fee_percent=Decimal(v.processing_fee_percent),
        gst_percent=Decimal(v.gst_percent),
    )


def late_of(v) -> dom.LateTerms:
    return dom.LateTerms(
        enabled=bool(v.late_charges_enabled),
        bounce_percent=Decimal(v.bounce_percent),
        bounce_cap_amount=Decimal(v.bounce_cap_amount),
        penal_annual_percent=Decimal(v.penal_annual_percent),
        penal_max_days=int(v.penal_max_days),
        total_cap_percent_of_due=Decimal(v.late_total_cap_percent_of_due),
    )


class PricingService:
    """Admin-configured, versioned pricing with maker-checker approval.

    A version is created as DRAFT by one admin and approved by a different
    one; nobody can edit it afterwards. An offer freezes the version in force
    on the day its draft is made, so a later change never reprices it."""

    def __init__(
        self,
        *,
        repository: PricingRepository,
        admin_user_repository: AdminUserRepository,
        admin_authorization_service: AdminAuthorizationService,
        audit_log_service: AuditLogService,
        settings: Settings,
    ):
        self.repository = repository
        self.admin_user_repository = admin_user_repository
        self.authz = admin_authorization_service
        self.audit = audit_log_service
        self.settings = settings

    # ------------------------------------------------------------ admin

    @staticmethod
    def _validate_late(late: dom.LateTerms) -> None:
        if not (Decimal(0) <= late.bounce_percent <= Decimal(100)):
            raise dom.PricingError("Bounce percent must be between 0 and 100")
        if late.bounce_cap_amount < 0:
            raise dom.PricingError("Bounce cap cannot be negative")
        if not (Decimal(0) <= late.penal_annual_percent <= Decimal(100)):
            raise dom.PricingError("Penal rate must be between 0 and 100 percent a year")
        if not 1 <= late.penal_max_days <= 365:
            raise dom.PricingError("Penal charge days must be between 1 and 365")
        if not (Decimal(0) < late.total_cap_percent_of_due <= Decimal(100)):
            raise dom.PricingError("Late charge cap must be above 0 and at most 100 percent")

    async def create_draft(
        self,
        *,
        actor_user_id: UUID,
        terms: dom.PricingTerms,
        late: dom.LateTerms,
        effective_from: date,
        note: str | None = None,
        request_id=None,
        ip_address=None,
    ) -> PricingVersion:
        await self.authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.PRICING_MANAGE
        )
        terms.validate()
        self._validate_late(late)
        if effective_from < today_ist():
            raise dom.PricingError("The effective date cannot be in the past")
        # Reject a combination that could never produce a payout.
        dom.quote(principal=Decimal("1000"), tenure_days=30, terms=terms, start=effective_from)
        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        version = await self.repository.create_version(
            status="DRAFT",
            effective_from=effective_from,
            annual_interest_percent=terms.annual_interest_percent,
            processing_fee_percent=terms.processing_fee_percent,
            gst_percent=terms.gst_percent,
            late_charges_enabled=late.enabled,
            bounce_percent=late.bounce_percent,
            bounce_cap_amount=late.bounce_cap_amount,
            penal_annual_percent=late.penal_annual_percent,
            penal_max_days=late.penal_max_days,
            late_total_cap_percent_of_due=late.total_cap_percent_of_due,
            note=note,
            created_by_admin_user_id=admin.id,
        )
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="PRICING_VERSION_CREATED",
            entity_type=ENTITY,
            entity_id=str(version.id),
            request_id=request_id,
            ip_address=ip_address,
            new_value=self._audit_view(version),
        )
        return version

    @staticmethod
    def _audit_view(v: PricingVersion) -> dict:
        return {
            "version": v.version,
            "status": v.status,
            "effective_from": v.effective_from.isoformat(),
            "annual_interest_percent": str(v.annual_interest_percent),
            "processing_fee_percent": str(v.processing_fee_percent),
            "gst_percent": str(v.gst_percent),
            "late_charges_enabled": v.late_charges_enabled,
        }

    async def _decide_lock(self, version_id: UUID) -> PricingVersion:
        version = await self.repository.get(version_id, for_update=True)
        if version is None:
            raise dom.PricingNotFound("Pricing version not found")
        if version.status != "DRAFT":
            raise dom.PricingConflict("This pricing version has already been decided")
        return version

    async def approve(
        self, *, actor_user_id: UUID, version_id: UUID, request_id=None, ip_address=None
    ) -> PricingVersion:
        await self.authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.PRICING_APPROVE
        )
        version = await self._decide_lock(version_id)
        admin = await self.admin_user_repository.get_by_user_id(actor_user_id)
        if admin.id == version.created_by_admin_user_id:
            raise PermissionError("A pricing version cannot be approved by the admin who created it")
        if not self.settings.ledger_interest_fee_posting_enabled:
            raise dom.PricingConflict(
                "Pricing cannot be activated until the accounting rules for posting "
                "interest, fees and GST are approved and enabled"
            )
        if version.effective_from < today_ist():
            raise dom.PricingConflict(
                "The effective date has already passed; create a new version"
            )
        old = self._audit_view(version)
        version.status = "APPROVED"
        version.approved_by_admin_user_id = admin.id
        version.decided_at = utcnow()
        await self.repository.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="PRICING_VERSION_APPROVED",
            entity_type=ENTITY,
            entity_id=str(version.id),
            request_id=request_id,
            ip_address=ip_address,
            old_value=old,
            new_value=self._audit_view(version),
        )
        return version

    async def reject(
        self, *, actor_user_id: UUID, version_id: UUID, reason: str, request_id=None, ip_address=None
    ) -> PricingVersion:
        await self.authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.PRICING_APPROVE
        )
        if not reason or not reason.strip():
            raise dom.PricingError("A reason is required")
        version = await self._decide_lock(version_id)
        old = self._audit_view(version)
        version.status = "REJECTED"
        version.reject_reason = reason.strip()
        version.decided_at = utcnow()
        await self.repository.session.flush()
        await self.audit.record_admin_action(
            actor_user_id=actor_user_id,
            action="PRICING_VERSION_REJECTED",
            entity_type=ENTITY,
            entity_id=str(version.id),
            request_id=request_id,
            ip_address=ip_address,
            reason=version.reject_reason,
            old_value=old,
            new_value=self._audit_view(version),
        )
        return version

    async def list_versions(self, *, actor_user_id: UUID) -> list[PricingVersion]:
        await self.authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.PRICING_READ
        )
        return await self.repository.list_versions()

    async def get_version(self, *, actor_user_id: UUID, version_id: UUID) -> PricingVersion:
        await self.authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.PRICING_READ
        )
        version = await self.repository.get(version_id)
        if version is None:
            raise dom.PricingNotFound("Pricing version not found")
        return version

    async def current(self, *, actor_user_id: UUID) -> PricingVersion | None:
        await self.authz.require_permission(
            user_id=actor_user_id, permission=AdminPermission.PRICING_READ
        )
        return await self.repository.get_effective(today_ist())

    # ------------------------------------------------------ offer side

    async def prepare(self, *, principal: Decimal, tenure_days: int) -> PreparedPricing | None:
        """Price an offer. None means no approved pricing is in force (the
        older free-form terms apply); an unusable configuration fails closed."""
        today = today_ist()
        version = await self.repository.get_effective(today)
        if version is None:
            return None
        if not self.settings.ledger_interest_fee_posting_enabled:
            raise dom.PricingConflict(
                "Pricing is configured but the accounting rules for posting interest, "
                "fees and GST are not enabled"
            )
        terms = terms_of(version)
        qt = dom.quote(principal=principal, tenure_days=tenure_days, terms=terms, start=today)
        return PreparedPricing(version=version, terms=terms, late=late_of(version), quote=qt)

    async def attach_snapshot(self, *, offer_id: UUID, prepared: PreparedPricing) -> LoanOfferPricing:
        qt, late, terms = prepared.quote, prepared.late, prepared.terms
        return await self.repository.add_snapshot(
            loan_offer_id=offer_id,
            pricing_version_id=prepared.version.id,
            principal=qt.principal,
            tenure_days=qt.months * dom.MONTH_DAYS,
            months=qt.months,
            annual_interest_percent=terms.annual_interest_percent,
            processing_fee_percent=terms.processing_fee_percent,
            gst_percent=terms.gst_percent,
            processing_fee=qt.processing_fee,
            gst_amount=qt.gst,
            net_payout=qt.net_payout,
            emi_amount=qt.emi,
            total_interest=qt.total_interest,
            total_repayable=qt.total_repayable,
            apr_percent=qt.apr_percent,
            late_charges_enabled=late.enabled,
            bounce_percent=late.bounce_percent,
            bounce_cap_amount=late.bounce_cap_amount,
            penal_annual_percent=late.penal_annual_percent,
            penal_max_days=late.penal_max_days,
            late_total_cap_percent_of_due=late.total_cap_percent_of_due,
        )

    async def snapshot_for_offer(self, offer_id: UUID) -> LoanOfferPricing | None:
        return await self.repository.get_snapshot(offer_id)
