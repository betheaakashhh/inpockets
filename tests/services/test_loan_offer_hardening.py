"""Unit tests for 2.8 offer hardening: acceptance, supersede, limits, expiry."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.loan_offer import (
    LoanOfferConflict,
    LoanOfferNotFound,
    effective_offer_status,
)
from app.services.loan_offer import LoanOfferService


def make_service(*, with_decisions=False):
    offers = AsyncMock()
    applications = AsyncMock()
    documents = AsyncMock()
    authorization = AsyncMock()
    audit = AsyncMock()
    decisions = AsyncMock() if with_decisions else None

    service = LoanOfferService(
        session=AsyncMock(),
        offer_repository=offers,
        application_repository=applications,
        document_repository=documents,
        admin_authorization_service=authorization,
        audit_log_service=audit,
        decision_repository=decisions,
    )
    service.admin_user_repository = AsyncMock()
    offers.get_accepted_for_application.return_value = None
    offers.list_open_for_application_for_update.return_value = []
    return service, offers, applications, audit, decisions


def offer_ns(*, status="ISSUED", user_id=None, expires_in=timedelta(days=1)):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        loan_application_id=uuid4(),
        user_id=user_id or uuid4(),
        version=2,
        status=status,
        principal_amount=Decimal("5000.00"),
        tenure_days=30,
        issued_at=now - timedelta(hours=1),
        expires_at=now + expires_in,
        accepted_at=None,
        kfs_document_id=uuid4(),
        agreement_document_id=uuid4(),
    )


# ---------------- acceptance ----------------


async def test_accept_records_customer_audit_with_exact_documents():
    service, offers, _, audit, _ = make_service()
    customer = uuid4()
    offer = offer_ns(user_id=customer)
    offers.get_by_id_for_update.return_value = offer

    result = await service.accept_offer(
        actor_user_id=customer,
        offer_id=offer.id,
        expected_version=2,
        kfs_document_id=offer.kfs_document_id,
        request_id="req-1",
    )

    assert result.status == "ACCEPTED"
    audit.record_customer_action.assert_awaited_once()
    kwargs = audit.record_customer_action.await_args.kwargs
    assert kwargs["action"] == "LOAN_OFFER_ACCEPTED"
    assert kwargs["request_id"] == "req-1"
    assert kwargs["new_value"]["kfs_document_id"] == str(offer.kfs_document_id)
    assert kwargs["new_value"]["agreement_document_id"] == str(
        offer.agreement_document_id
    )
    assert kwargs["new_value"]["version"] == 2


async def test_accept_is_idempotent_for_already_accepted_offer():
    service, offers, _, audit, _ = make_service()
    customer = uuid4()
    offer = offer_ns(status="ACCEPTED", user_id=customer)
    offer.accepted_at = datetime.now(UTC)
    offers.get_by_id_for_update.return_value = offer

    result = await service.accept_offer(actor_user_id=customer, offer_id=offer.id)

    assert result is offer
    offers.update.assert_not_awaited()
    audit.record_customer_action.assert_not_awaited()


async def test_accept_rejects_stale_version():
    service, offers, _, audit, _ = make_service()
    customer = uuid4()
    offer = offer_ns(user_id=customer)
    offers.get_by_id_for_update.return_value = offer

    with pytest.raises(LoanOfferConflict, match="changed"):
        await service.accept_offer(
            actor_user_id=customer, offer_id=offer.id, expected_version=1
        )

    assert offer.status == "ISSUED"
    offers.update.assert_not_awaited()


async def test_accept_rejects_wrong_kfs_document():
    service, offers, _, _, _ = make_service()
    customer = uuid4()
    offer = offer_ns(user_id=customer)
    offers.get_by_id_for_update.return_value = offer

    with pytest.raises(LoanOfferConflict, match="Key Facts Statement"):
        await service.accept_offer(
            actor_user_id=customer,
            offer_id=offer.id,
            expected_version=2,
            kfs_document_id=uuid4(),
        )

    assert offer.status == "ISSUED"


@pytest.mark.parametrize("status", ["DRAFT"])
async def test_customer_cannot_see_or_accept_draft(status):
    service, offers, _, _, _ = make_service()
    customer = uuid4()
    offer = offer_ns(status=status, user_id=customer)
    offers.get_by_id_for_update.return_value = offer
    offers.get_by_id.return_value = offer

    with pytest.raises(LoanOfferNotFound):
        await service.accept_offer(actor_user_id=customer, offer_id=offer.id)
    with pytest.raises(LoanOfferNotFound):
        await service.decline_offer(actor_user_id=customer, offer_id=offer.id)
    with pytest.raises(LoanOfferNotFound):
        await service.get_for_customer(actor_user_id=customer, offer_id=offer.id)


@pytest.mark.parametrize("status", ["CANCELLED", "DECLINED", "EXPIRED"])
async def test_closed_offers_cannot_be_accepted(status):
    service, offers, _, _, _ = make_service()
    customer = uuid4()
    offer = offer_ns(status=status, user_id=customer)
    offers.get_by_id_for_update.return_value = offer

    with pytest.raises(LoanOfferConflict, match="Only issued"):
        await service.accept_offer(actor_user_id=customer, offer_id=offer.id)


async def test_accept_after_expiry_persists_expired_and_audits():
    service, offers, _, audit, _ = make_service()
    customer = uuid4()
    offer = offer_ns(user_id=customer, expires_in=timedelta(seconds=-1))
    offers.get_by_id_for_update.return_value = offer

    result = await service.accept_offer(actor_user_id=customer, offer_id=offer.id)

    assert result.status == "EXPIRED"
    assert result.accepted_at is None
    assert audit.record_customer_action.await_args.kwargs["action"] == "LOAN_OFFER_EXPIRED"


async def test_accept_requires_documents_on_offer():
    service, offers, _, _, _ = make_service()
    customer = uuid4()
    offer = offer_ns(user_id=customer)
    offer.kfs_document_id = None
    offers.get_by_id_for_update.return_value = offer

    with pytest.raises(LoanOfferConflict, match="documents"):
        await service.accept_offer(actor_user_id=customer, offer_id=offer.id)
    assert offer.status == "ISSUED"


async def test_decline_is_idempotent_and_audited():
    service, offers, _, audit, _ = make_service()
    customer = uuid4()
    offer = offer_ns(user_id=customer)
    offers.get_by_id_for_update.return_value = offer

    first = await service.decline_offer(actor_user_id=customer, offer_id=offer.id)
    assert first.status == "DECLINED"
    assert audit.record_customer_action.await_args.kwargs["action"] == "LOAN_OFFER_DECLINED"

    audit.record_customer_action.reset_mock()
    again = await service.decline_offer(actor_user_id=customer, offer_id=offer.id)
    assert again.status == "DECLINED"
    audit.record_customer_action.assert_not_awaited()


async def test_list_for_customer_hides_drafts():
    service, offers, _, _, _ = make_service()
    customer = uuid4()
    draft = offer_ns(status="DRAFT", user_id=customer)
    issued = offer_ns(status="ISSUED", user_id=customer)
    offers.list_by_user_id.return_value = [draft, issued]

    result = await service.list_for_customer(actor_user_id=customer)

    assert result == [issued]


# ---------------- amount limits ----------------


def approved_application(requested="10000.00"):
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        status="APPROVED",
        requested_amount=Decimal(requested),
    )


async def test_draft_principal_cannot_exceed_requested_amount():
    service, offers, applications, audit, _ = make_service()
    applications.get_by_id_for_update.return_value = approved_application("5000.00")

    with pytest.raises(ValueError, match="requested amount"):
        await service.create_draft(
            actor_user_id=uuid4(),
            loan_application_id=uuid4(),
            principal_amount=Decimal("5000.01"),
            tenure_days=30,
            commercial_terms={},
        )
    offers.create.assert_not_awaited()
    audit.record_admin_action.assert_not_awaited()


async def test_draft_principal_cannot_exceed_policy_max_eligible():
    service, offers, applications, _, decisions = make_service(with_decisions=True)
    applications.get_by_id_for_update.return_value = approved_application("10000.00")
    decisions.get_latest_for_loan_application.return_value = SimpleNamespace(
        max_eligible_amount=Decimal("9000.00")
    )

    with pytest.raises(ValueError, match="maximum eligible"):
        await service.create_draft(
            actor_user_id=uuid4(),
            loan_application_id=uuid4(),
            principal_amount=Decimal("9500.00"),
            tenure_days=30,
            commercial_terms={},
        )
    offers.create.assert_not_awaited()


async def test_draft_at_exactly_max_eligible_is_allowed():
    service, offers, applications, _, decisions = make_service(with_decisions=True)
    application = approved_application("10000.00")
    applications.get_by_id_for_update.return_value = application
    decisions.get_latest_for_loan_application.return_value = SimpleNamespace(
        max_eligible_amount=Decimal("9000.00")
    )
    offers.get_latest_for_application_for_update.return_value = None
    service.admin_user_repository.get_by_user_id.return_value = SimpleNamespace(
        id=uuid4(), is_active=True
    )
    offers.create.return_value = SimpleNamespace(
        id=uuid4(), version=1, principal_amount=Decimal("9000.00"), tenure_days=30
    )

    await service.create_draft(
        actor_user_id=uuid4(),
        loan_application_id=application.id,
        principal_amount=Decimal("9000.00"),
        tenure_days=30,
        commercial_terms={},
    )
    offers.create.assert_awaited_once()


async def test_no_new_draft_after_acceptance():
    service, offers, applications, _, _ = make_service()
    applications.get_by_id_for_update.return_value = approved_application()
    offers.get_accepted_for_application.return_value = offer_ns(status="ACCEPTED")

    with pytest.raises(LoanOfferConflict, match="already been accepted"):
        await service.create_draft(
            actor_user_id=uuid4(),
            loan_application_id=uuid4(),
            principal_amount=Decimal("1000.00"),
            tenure_days=30,
            commercial_terms={},
        )
    offers.create.assert_not_awaited()


# ---------------- supersede ----------------


def immutable_doc(owner_id, doc_type, offer):
    return SimpleNamespace(
        id=uuid4(),
        owner_type="USER",
        owner_id=owner_id,
        document_type=doc_type,
        is_immutable=True,
        content_type="application/pdf",
        loan_offer_id=offer.id,
        loan_offer_version=offer.version,
        template_key="t",
        template_version="v1",
    )


async def test_issuing_new_version_cancels_previous_issued_offer():
    service, offers, applications, audit, _ = make_service()
    application = SimpleNamespace(id=uuid4(), user_id=uuid4(), status="APPROVED")
    draft = offer_ns(status="DRAFT")
    draft.loan_application_id = application.id
    old = offer_ns(status="ISSUED")
    old.version = 1
    kfs = immutable_doc(application.user_id, "KFS", draft)
    agreement = immutable_doc(application.user_id, "LOAN_AGREEMENT", draft)

    offers.get_by_id.return_value = draft
    offers.get_by_id_for_update.return_value = draft
    applications.get_by_id_for_update.return_value = application
    offers.list_open_for_application_for_update.return_value = [old]
    service.document_repository.get_by_id.side_effect = [kfs, agreement]

    await service.issue_offer(
        actor_user_id=uuid4(),
        offer_id=draft.id,
        kfs_document_id=kfs.id,
        agreement_document_id=agreement.id,
    )

    assert old.status == "CANCELLED"
    assert draft.status == "ISSUED"
    # old offer is flushed before the new one becomes ISSUED
    updated = [c.args[0] for c in offers.update.await_args_list]
    assert updated == [old, draft]
    actions = [c.kwargs["action"] for c in audit.record_admin_action.await_args_list]
    assert actions == ["LOAN_OFFER_SUPERSEDED", "LOAN_OFFER_ISSUED"]


async def test_cannot_issue_when_another_offer_already_accepted():
    service, offers, applications, audit, _ = make_service()
    application = SimpleNamespace(id=uuid4(), user_id=uuid4(), status="APPROVED")
    draft = offer_ns(status="DRAFT")
    draft.loan_application_id = application.id
    accepted = offer_ns(status="ACCEPTED")
    accepted.version = 1
    kfs = immutable_doc(application.user_id, "KFS", draft)
    agreement = immutable_doc(application.user_id, "LOAN_AGREEMENT", draft)

    offers.get_by_id.return_value = draft
    offers.get_by_id_for_update.return_value = draft
    applications.get_by_id_for_update.return_value = application
    offers.list_open_for_application_for_update.return_value = [accepted]
    service.document_repository.get_by_id.side_effect = [kfs, agreement]

    with pytest.raises(LoanOfferConflict, match="already been accepted"):
        await service.issue_offer(
            actor_user_id=uuid4(),
            offer_id=draft.id,
            kfs_document_id=kfs.id,
            agreement_document_id=agreement.id,
        )
    assert draft.status == "DRAFT"
    assert accepted.status == "ACCEPTED"


# ---------------- expiry ----------------


async def test_expire_due_offers_marks_each_and_audits_as_system():
    service, offers, _, audit, _ = make_service()
    due = [offer_ns(expires_in=timedelta(seconds=-5)) for _ in range(3)]
    offers.list_due_for_expiry_for_update.return_value = due

    count = await service.expire_due_offers(batch_size=10)

    assert count == 3
    assert all(o.status == "EXPIRED" for o in due)
    assert audit.record_system_action.await_count == 3
    assert offers.list_due_for_expiry_for_update.await_args.kwargs["limit"] == 10


async def test_expire_due_offers_noop_when_nothing_due():
    service, offers, _, audit, _ = make_service()
    offers.list_due_for_expiry_for_update.return_value = []

    assert await service.expire_due_offers() == 0
    audit.record_system_action.assert_not_awaited()


async def test_expire_due_offers_rejects_bad_batch_size():
    service, *_ = make_service()
    with pytest.raises(ValueError):
        await service.expire_due_offers(batch_size=0)


def test_effective_status_boundaries():
    now = datetime.now(UTC)
    assert effective_offer_status(status="ISSUED", expires_at=now, now=now) == "EXPIRED"
    assert (
        effective_offer_status(
            status="ISSUED", expires_at=now + timedelta(seconds=1), now=now
        )
        == "ISSUED"
    )
    # only ISSUED is reinterpreted
    assert effective_offer_status(status="ACCEPTED", expires_at=now, now=now) == "ACCEPTED"
    assert effective_offer_status(status="DRAFT", expires_at=None, now=now) == "DRAFT"
