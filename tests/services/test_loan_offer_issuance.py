from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.domain.loan_offer import LoanOfferConflict, LoanOfferNotFound
from app.services.loan_offer_issuance import LoanOfferIssuanceService
from app.services.offer_templates import OfferTemplateRegistry


def build(*, environment="development", offer_status="DRAFT", app_status="APPROVED"):
    user_id = uuid4()
    application = SimpleNamespace(id=uuid4(), user_id=user_id, status=app_status)
    offer = SimpleNamespace(
        id=uuid4(),
        loan_application_id=application.id,
        user_id=user_id,
        version=3,
        status=offer_status,
        principal_amount=Decimal("5000.00"),
        tenure_days=30,
        commercial_terms={},
        expires_at=None,
    )

    offer_service = MagicMock()
    offer_service.admin_authorization_service.require_permission = AsyncMock()
    issued = SimpleNamespace(status="ISSUED")
    offer_service.issue_offer = AsyncMock(return_value=issued)

    documents = MagicMock()
    stored = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    documents.store_document = AsyncMock(side_effect=stored)

    offers = AsyncMock()
    offers.get_by_id.return_value = offer
    offers.get_by_id_for_update.return_value = offer
    applications = AsyncMock()
    applications.get_by_id_for_update.return_value = application

    pdf = MagicMock()
    pdf.generate_kfs.return_value = b"%PDF-kfs"
    pdf.generate_agreement.return_value = b"%PDF-agreement"

    service = LoanOfferIssuanceService(
        offer_service=offer_service,
        document_service=documents,
        offer_repository=offers,
        application_repository=applications,
        pdf_generator=pdf,
        settings=SimpleNamespace(
            environment=environment,
            loan_offer_validity_hours=48,
            loan_offer_kfs_template_version="draft-v1",
            loan_offer_agreement_template_version="draft-v1",
            lender_name=None,
            loan_offer_template_dir=None,
        ),
        template_registry=OfferTemplateRegistry(),
    )
    return service, offer_service, documents, pdf, offer, application, stored, issued


async def test_issue_generates_stores_immutable_docs_and_issues():
    service, offer_service, documents, pdf, offer, application, stored, issued = build()
    actor = uuid4()

    result = await service.issue(actor_user_id=actor, offer_id=offer.id, request_id="r1")

    assert result is issued
    calls = documents.store_document.await_args_list
    assert [c.kwargs["document_type"] for c in calls] == ["KFS", "LOAN_AGREEMENT"]
    for call in calls:
        kw = call.kwargs
        assert kw["owner_type"] == "USER"
        assert kw["owner_id"] == application.user_id
        assert kw["immutable"] is True
        assert kw["content_type"] == "application/pdf"
        assert kw["loan_offer_id"] == offer.id
        assert kw["loan_offer_version"] == 3
        assert kw["template_version"] == "draft-v1"
    issue_kwargs = offer_service.issue_offer.await_args.kwargs
    assert issue_kwargs["kfs_document_id"] == stored[0].id
    assert issue_kwargs["agreement_document_id"] == stored[1].id
    assert issue_kwargs["expires_in"] == timedelta(hours=48)
    assert issue_kwargs["request_id"] == "r1"


async def test_explicit_validity_overrides_configured_default():
    service, offer_service, *_ , offer, _, _, _ = build()
    await service.issue(
        actor_user_id=uuid4(), offer_id=offer.id, validity=timedelta(hours=2)
    )
    assert offer_service.issue_offer.await_args.kwargs["expires_in"] == timedelta(hours=2)


async def test_authorization_failure_stops_before_any_generation_or_storage():
    service, offer_service, documents, pdf, offer, *_ = build()
    offer_service.admin_authorization_service.require_permission.side_effect = (
        PermissionError("permission denied")
    )

    with pytest.raises(PermissionError):
        await service.issue(actor_user_id=uuid4(), offer_id=offer.id)

    pdf.generate_kfs.assert_not_called()
    documents.store_document.assert_not_awaited()
    offer_service.issue_offer.assert_not_awaited()


async def test_draft_templates_are_refused_in_production():
    service, offer_service, documents, pdf, offer, *_ = build(environment="production")

    with pytest.raises(LoanOfferConflict, match="not approved"):
        await service.issue(actor_user_id=uuid4(), offer_id=offer.id)

    pdf.generate_kfs.assert_not_called()
    documents.store_document.assert_not_awaited()


@pytest.mark.parametrize("status", ["ISSUED", "ACCEPTED", "CANCELLED", "EXPIRED"])
async def test_non_draft_offer_is_not_regenerated(status):
    service, offer_service, documents, pdf, offer, *_ = build(offer_status=status)

    with pytest.raises(LoanOfferConflict, match="draft"):
        await service.issue(actor_user_id=uuid4(), offer_id=offer.id)

    pdf.generate_kfs.assert_not_called()
    documents.store_document.assert_not_awaited()


async def test_unapproved_application_blocks_issue():
    service, offer_service, documents, pdf, offer, *_ = build(app_status="REJECTED")

    with pytest.raises(LoanOfferConflict, match="approved"):
        await service.issue(actor_user_id=uuid4(), offer_id=offer.id)
    documents.store_document.assert_not_awaited()


async def test_missing_offer_is_not_found():
    service, _, documents, *_ = build()
    service.offer_repository.get_by_id.return_value = None

    with pytest.raises(LoanOfferNotFound):
        await service.issue(actor_user_id=uuid4(), offer_id=uuid4())
    documents.store_document.assert_not_awaited()
