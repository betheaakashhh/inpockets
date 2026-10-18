from datetime import datetime, timedelta, timezone

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from decimal import Decimal
import pytest

from app.domain.admin import AdminPermission
from app.services.loan_offer import LoanOfferService


def make_service():
    session = AsyncMock()
    offers = AsyncMock()
    applications = AsyncMock()
    documents = AsyncMock()
    authorization = AsyncMock()
    audit = AsyncMock()

    service = LoanOfferService(
        session=session,
        offer_repository=offers,
        application_repository=applications,
        document_repository=documents,
        admin_authorization_service=authorization,
        audit_log_service=audit,
    )
    service.admin_user_repository = AsyncMock()
    # Safe defaults for the guard queries added in 2.8 hardening.
    offers.get_accepted_for_application.return_value = None
    offers.list_open_for_application_for_update.return_value = []

    return service, offers, applications, documents, authorization, audit


def make_offer(*, status="DRAFT", user_id=None, application_id=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        loan_application_id=application_id or uuid4(),
        user_id=user_id or uuid4(),
        version=1,
        principal_amount=Decimal("10000.00"),
        tenure_days=30,
        status=status,
        issued_at=None,
        expires_at=None,
        accepted_at=None,
        kfs_document_id=None,
        agreement_document_id=None,
    )



def make_document(
    *,
    owner_id,
    document_type,
    immutable=True,
    loan_offer_id=None,
    loan_offer_version=None,
    template_key="kfs",
    template_version="v1",
):
    return SimpleNamespace(
        id=uuid4(),
        owner_type="USER",
        owner_id=owner_id,
        document_type=document_type,
        is_immutable=immutable,
        content_type="application/pdf",
        loan_offer_id=loan_offer_id,
        loan_offer_version=loan_offer_version,
        template_key=template_key,
        template_version=template_version,
    )



@pytest.mark.asyncio
async def test_unauthorized_admin_cannot_issue_offer():
    service, offers, applications, documents, authorization, audit = make_service()
    authorization.require_permission.side_effect = PermissionError("permission denied")

    with pytest.raises(PermissionError, match="permission denied"):
        await service.issue_offer(
            actor_user_id=uuid4(),
            offer_id=uuid4(),
            kfs_document_id=uuid4(),
            agreement_document_id=uuid4(),
        )

    authorization.require_permission.assert_awaited_once_with(
        user_id=authorization.require_permission.call_args.kwargs["user_id"],
        permission=AdminPermission.LOAN_OFFER_ISSUE,
    )
    offers.get_by_id.assert_not_awaited()
    applications.get_by_id_for_update.assert_not_awaited()
    audit.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorized_admin_can_issue_offer_with_immutable_documents():
    service, offers, applications, documents, authorization, audit = make_service()

    application = SimpleNamespace(id=uuid4(), user_id=uuid4(), status="APPROVED")
    offer = make_offer(application_id=application.id)
    kfs = make_document(
    owner_id=application.user_id,
    document_type="KFS",
    loan_offer_id=offer.id,
    loan_offer_version=offer.version,
    template_key="kfs",
    template_version="v1",
)

    agreement = make_document(
    owner_id=application.user_id,
    document_type="LOAN_AGREEMENT",
    loan_offer_id=offer.id,
    loan_offer_version=offer.version,
    template_key="loan-agreement",
    template_version="v1",
)

    offers.get_by_id.return_value = offer
    offers.get_by_id_for_update.return_value = offer
    applications.get_by_id_for_update.return_value = application
    documents.get_by_id.side_effect = [kfs, agreement]

    result = await service.issue_offer(
        actor_user_id=uuid4(),
        offer_id=offer.id,
        kfs_document_id=kfs.id,
        agreement_document_id=agreement.id,
    )

    assert result is offer
    assert offer.status == "ISSUED"
    assert offer.kfs_document_id == kfs.id
    assert offer.agreement_document_id == agreement.id
    assert offer.issued_at is not None
    assert offer.expires_at > offer.issued_at
    offers.update.assert_awaited_once_with(offer)
    audit.record_admin_action.assert_awaited_once()
    assert audit.record_admin_action.await_args.kwargs["action"] == "LOAN_OFFER_ISSUED"


@pytest.mark.asyncio
async def test_offer_cannot_be_issued_for_unapproved_application():
    service, offers, applications, documents, authorization, audit = make_service()

    application = SimpleNamespace(id=uuid4(), user_id=uuid4(), status="MANUAL_REVIEW")
    offer = make_offer(application_id=application.id)
    offers.get_by_id.return_value = offer
    offers.get_by_id_for_update.return_value = offer
    applications.get_by_id_for_update.return_value = application

    with pytest.raises(ValueError, match="approved application"):
        await service.issue_offer(
            actor_user_id=uuid4(),
            offer_id=offer.id,
            kfs_document_id=uuid4(),
            agreement_document_id=uuid4(),
        )

    documents.get_by_id.assert_not_awaited()
    offers.update.assert_not_awaited()
    audit.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_mutable_kfs_document_is_rejected():
    service, offers, applications, documents, authorization, audit = make_service()

    application = SimpleNamespace(id=uuid4(), user_id=uuid4(), status="APPROVED")
    offer = make_offer(application_id=application.id)
    kfs = make_document(
        owner_id=application.user_id,
        document_type="KFS",
        immutable=False,
    )

    offers.get_by_id.return_value = offer
    offers.get_by_id_for_update.return_value = offer
    applications.get_by_id_for_update.return_value = application
    documents.get_by_id.return_value = kfs

    with pytest.raises(ValueError, match="must be immutable"):
        await service.issue_offer(
            actor_user_id=uuid4(),
            offer_id=offer.id,
            kfs_document_id=kfs.id,
            agreement_document_id=uuid4(),
        )

    offers.update.assert_not_awaited()
    audit.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_customer_cannot_accept_another_users_offer():
    service, offers, applications, documents, authorization, audit = make_service()

    offer = make_offer(status="ISSUED", user_id=uuid4())
    offer.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    offers.get_by_id_for_update.return_value = offer
    customer_id = uuid4()

    with pytest.raises(ValueError, match="Loan offer not found"):
        await service.accept_offer(
            actor_user_id=customer_id,
            offer_id=offer.id,
        )

    offers.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_offer_cannot_be_accepted():
    service, offers, applications, documents, authorization, audit = make_service()

    customer_id = uuid4()
    offer = make_offer(status="ISSUED", user_id=customer_id)
    offer.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    offers.get_by_id_for_update.return_value = offer

    result = await service.accept_offer(
        actor_user_id=customer_id,
        offer_id=offer.id,
    )

    assert result.status == "EXPIRED"
    assert result.accepted_at is None
    offers.update.assert_awaited_once_with(offer)


@pytest.mark.asyncio
async def test_accepting_valid_offer_records_acceptance():
    service, offers, applications, documents, authorization, audit = make_service()

    customer_id = uuid4()
    offer = make_offer(status="ISSUED", user_id=customer_id)
    offer.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    offer.kfs_document_id = uuid4()
    offer.agreement_document_id = uuid4()
    offers.get_by_id_for_update.return_value = offer

    result = await service.accept_offer(
        actor_user_id=customer_id,
        offer_id=offer.id,
    )

    assert result.status == "ACCEPTED"
    assert result.accepted_at is not None
    assert result.accepted_at.tzinfo is not None
    offers.update.assert_awaited_once_with(offer)

@pytest.mark.asyncio
async def test_cancel_offer_requires_permission():
    service, offers, applications, documents, authorization, audit = make_service()
    authorization.require_permission.side_effect = PermissionError("permission denied")

    with pytest.raises(PermissionError, match="permission denied"):
        await service.cancel_offer(
            actor_user_id=uuid4(),
            offer_id=uuid4(),
            reason="Incorrect terms",
        )

    offers.get_by_id_for_update.assert_not_awaited()
    offers.update.assert_not_awaited()
    audit.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_offer_requires_nonblank_reason():
    service, offers, applications, documents, authorization, audit = make_service()

    with pytest.raises(ValueError, match="cancellation reason is required"):
        await service.cancel_offer(
            actor_user_id=uuid4(),
            offer_id=uuid4(),
            reason="   ",
        )

    offers.get_by_id_for_update.assert_not_awaited()
    offers.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_offer_updates_status_and_audits_reason():
    service, offers, applications, documents, authorization, audit = make_service()
    offer = make_offer(status="ISSUED")
    offers.get_by_id_for_update.return_value = offer

    result = await service.cancel_offer(
        actor_user_id=uuid4(),
        offer_id=offer.id,
        reason="  Customer eligibility changed  ",
    )

    assert result is offer
    assert offer.status == "CANCELLED"
    offers.update.assert_awaited_once_with(offer)
    audit.record_admin_action.assert_awaited_once()
    assert audit.record_admin_action.await_args.kwargs["action"] == "LOAN_OFFER_CANCELLED"
    assert (
    audit.record_admin_action.await_args.kwargs["new_value"]["reason"]
    == "Customer eligibility changed"
    )

@pytest.mark.asyncio
async def test_expire_offer_rejects_offer_that_has_not_expired():
    service, offers, applications, documents, authorization, audit = make_service()
    offer = make_offer(status="ISSUED")
    offer.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    offers.get_by_id_for_update.return_value = offer

    with pytest.raises(ValueError, match="has not expired"):
        await service.expire_offer(offer_id=offer.id)

    offers.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_offer_marks_expired_offer_as_expired():
    service, offers, applications, documents, authorization, audit = make_service()
    customer_id = uuid4()
    offer = make_offer(status="ISSUED", user_id=customer_id)
    offer.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    offers.get_by_id_for_update.return_value = offer

    result = await service.decline_offer(
        actor_user_id=customer_id,
        offer_id=offer.id,
    )

    assert result.status == "EXPIRED"
    offers.update.assert_awaited_once_with(offer)
    
@pytest.mark.asyncio
async def test_create_draft_requires_approved_application():
    service, offers, applications, documents, authorization, audit = make_service()
    application = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        status="MANUAL_REVIEW",
        requested_amount=Decimal("10000.00"),
    )
    applications.get_by_id_for_update.return_value = application

    with pytest.raises(ValueError, match="approved application"):
        await service.create_draft(
            actor_user_id=uuid4(),
            loan_application_id=application.id,
            principal_amount=Decimal("10000.00"),
            tenure_days=30,
            commercial_terms={"interest_rate": "12%"},
        )

    offers.create.assert_not_awaited()
    audit.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_draft_starts_at_version_one():
    service, offers, applications, documents, authorization, audit = make_service()
    actor_id = uuid4()
    application = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        status="APPROVED",
        requested_amount=Decimal("10000.00"),
    )
    admin = SimpleNamespace(id=uuid4(), is_active=True)
    draft = make_offer(application_id=application.id)
    draft.version = 1
    draft.principal_amount = Decimal("10000.00")
    draft.tenure_days = 30

    applications.get_by_id_for_update.return_value = application
    offers.get_latest_for_application_for_update.return_value = None
    service.admin_user_repository.get_by_user_id.return_value = admin
    offers.create.return_value = draft

    result = await service.create_draft(
        actor_user_id=actor_id,
        loan_application_id=application.id,
        principal_amount=Decimal("10000.00"),
        tenure_days=30,
        commercial_terms={"interest_rate": "12%"},
    )

    assert result.version == 1
    offers.create.assert_awaited_once()
    assert offers.create.await_args.kwargs["version"] == 1
    assert offers.create.await_args.kwargs["created_by_admin_user_id"] == admin.id
    audit.record_admin_action.assert_awaited_once()
    assert audit.record_admin_action.await_args.kwargs["action"] == "LOAN_OFFER_DRAFT_CREATED"


@pytest.mark.asyncio
async def test_create_draft_increments_existing_version():
    service, offers, applications, documents, authorization, audit = make_service()
    application = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        status="APPROVED",
        requested_amount=Decimal("10000.00"),
    )
    admin = SimpleNamespace(id=uuid4(), is_active=True)
    latest = SimpleNamespace(version=3)
    draft = make_offer(application_id=application.id)
    draft.version = 4
    draft.principal_amount = Decimal("10000.00")
    draft.tenure_days = 30

    applications.get_by_id_for_update.return_value = application
    offers.get_latest_for_application_for_update.return_value = latest
    service.admin_user_repository.get_by_user_id.return_value = admin
    offers.create.return_value = draft

    result = await service.create_draft(
        actor_user_id=uuid4(),
        loan_application_id=application.id,
        principal_amount=Decimal("10000.00"),
        tenure_days=30,
        commercial_terms={"interest_rate": "12%"},
    )

    assert result.version == 4
    assert offers.create.await_args.kwargs["version"] == 4


@pytest.mark.asyncio
async def test_issue_offer_rejects_document_for_different_offer():
    service, offers, applications, documents, authorization, audit = make_service()
    offer = make_offer()
    document = make_document(
        owner_id=offer.user_id,
        document_type="KFS",
        loan_offer_id=uuid4(),
        loan_offer_version=offer.version,
    )
    documents.get_by_id.return_value = document

    with pytest.raises(ValueError, match="different loan offer"):
        await service._require_immutable_document(
            document_id=document.id,
            expected_type="KFS",
            expected_owner_id=offer.user_id,
            expected_offer_id=offer.id,
            expected_offer_version=offer.version,
        )


@pytest.mark.asyncio
async def test_issue_offer_rejects_wrong_document_offer_version():
    service, offers, applications, documents, authorization, audit = make_service()
    offer = make_offer()
    document = make_document(
        owner_id=offer.user_id,
        document_type="KFS",
        loan_offer_id=offer.id,
        loan_offer_version=offer.version + 1,
    )
    documents.get_by_id.return_value = document

    with pytest.raises(ValueError, match="incorrect loan offer version"):
        await service._require_immutable_document(
            document_id=document.id,
            expected_type="KFS",
            expected_owner_id=offer.user_id,
            expected_offer_id=offer.id,
            expected_offer_version=offer.version,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("template_key", None, "template key"),
        ("template_key", "   ", "template key"),
        ("template_version", None, "template version"),
        ("template_version", "   ", "template version"),
    ],
)
async def test_issue_offer_rejects_missing_template_metadata(
    field,
    value,
    message,
):
    service, offers, applications, documents, authorization, audit = make_service()
    offer = make_offer()
    document = make_document(
        owner_id=offer.user_id,
        document_type="KFS",
        loan_offer_id=offer.id,
        loan_offer_version=offer.version,
    )
    setattr(document, field, value)
    documents.get_by_id.return_value = document

    with pytest.raises(ValueError, match=message):
        await service._require_immutable_document(
            document_id=document.id,
            expected_type="KFS",
            expected_owner_id=offer.user_id,
            expected_offer_id=offer.id,
            expected_offer_version=offer.version,
        )
