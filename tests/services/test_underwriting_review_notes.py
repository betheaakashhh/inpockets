from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.admin import AdminRole
from app.models.admin_user import AdminUser
from app.models.loan_application import LoanApplication
from app.models.underwriting_review_case import UnderwritingReviewCase
from app.repositories.underwriting_review_case import (
    UnderwritingReviewCaseRepository,
)
from app.services.underwriting_review_notes import (
    UnderwritingReviewNotesService,
)


async def create_review_case(db_session, user):
    application = LoanApplication(
        id=uuid4(),
        application_number=f"TEST-{uuid4().hex[:12].upper()}",
        user_id=user.id,
        status="SUBMITTED",
        requested_amount=Decimal("10000.00"),
        requested_tenure_days=30,
    )

    db_session.add(application)
    await db_session.flush()

    repository = UnderwritingReviewCaseRepository(db_session)

    case = await repository.create(
        loan_application_id=application.id,
        user_id=user.id,
    )

    return case


def make_service(db_session):
    audit_log_service = AsyncMock()

    service = UnderwritingReviewNotesService(
        session=db_session,
        audit_log_service=audit_log_service,
    )

    return service, audit_log_service


@pytest.mark.asyncio
async def test_underwriting_reviewer_can_add_note(
    db_session,
    user,
    admin_user,
):
    admin_user.role = AdminRole.UNDERWRITER.value
    await db_session.flush()

    case = await create_review_case(db_session, user)

    service, audit_log_service = make_service(db_session)

    note = await service.add_note(
        actor_user_id=user.id,
        review_case_id=case.id,
        content="Income documents reviewed.",
    )

    assert note.review_case_id == case.id
    assert note.author_admin_user_id == admin_user.id
    assert note.content == "Income documents reviewed."

    audit_log_service.record_admin_action.assert_awaited_once()
    audit = audit_log_service.record_admin_action.await_args.kwargs
    assert audit["actor_user_id"] == user.id
    assert audit["action"] == "UNDERWRITING_REVIEW_NOTE_ADDED"
    assert audit["entity_type"] == "underwriting_review_note"
    assert audit["entity_id"] == str(note.id)
    assert audit["event_metadata"]["review_case_id"] == str(case.id)


@pytest.mark.asyncio
async def test_underwriting_reviewer_can_add_evidence(
    db_session,
    user,
    admin_user,
):
    admin_user.role = AdminRole.UNDERWRITER.value
    await db_session.flush()

    case = await create_review_case(db_session, user)

    service, audit_log_service = make_service(db_session)

    evidence = await service.add_evidence(
        actor_user_id=user.id,
        review_case_id=case.id,
        evidence_type="KYC_DOCUMENT",
        reference="document:123",
        evidence_metadata={
            "document_type": "PAN",
        },
    )

    assert evidence.review_case_id == case.id
    assert evidence.added_by_admin_user_id == admin_user.id
    assert evidence.evidence_type == "KYC_DOCUMENT"

    audit_log_service.record_admin_action.assert_awaited_once()
    audit = audit_log_service.record_admin_action.await_args.kwargs
    assert audit["actor_user_id"] == user.id
    assert audit["action"] == "UNDERWRITING_REVIEW_EVIDENCE_ADDED"
    assert audit["entity_type"] == "underwriting_review_evidence"
    assert audit["entity_id"] == str(evidence.id)
    assert audit["event_metadata"]["review_case_id"] == str(case.id)

    # Evidence contents/references should not be unnecessarily duplicated
    # into the audit record.
    assert audit["old_value"] is None
    assert audit["new_value"] is None


@pytest.mark.asyncio
async def test_non_underwriting_role_cannot_add_note(
    db_session,
    user,
    admin_user,
):
    admin_user.role = AdminRole.KYC_REVIEWER.value
    await db_session.flush()

    case = await create_review_case(db_session, user)

    service, audit_log_service = make_service(db_session)

    with pytest.raises(PermissionError):
        await service.add_note(
            actor_user_id=user.id,
            review_case_id=case.id,
            content="Should be denied.",
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_underwriting_role_cannot_add_evidence(
    db_session,
    user,
    admin_user,
):
    admin_user.role = AdminRole.FRAUD_REVIEWER.value
    await db_session.flush()

    case = await create_review_case(db_session, user)

    service, audit_log_service = make_service(db_session)

    with pytest.raises(PermissionError):
        await service.add_evidence(
            actor_user_id=user.id,
            review_case_id=case.id,
            evidence_type="KYC_DOCUMENT",
            reference="document:123",
            evidence_metadata={},
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_note_is_rejected(
    db_session,
    user,
    admin_user,
):
    admin_user.role = AdminRole.UNDERWRITER.value
    await db_session.flush()

    case = await create_review_case(db_session, user)

    service, audit_log_service = make_service(db_session)

    with pytest.raises(ValueError, match="review note content is required"):
        await service.add_note(
            actor_user_id=user.id,
            review_case_id=case.id,
            content="   ",
        )

    audit_log_service.record_admin_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_evidence_reference_is_rejected(
    db_session,
    user,
    admin_user,
):
    admin_user.role = AdminRole.UNDERWRITER.value
    await db_session.flush()

    case = await create_review_case(db_session, user)

    service, audit_log_service = make_service(db_session)

    with pytest.raises(ValueError, match="evidence reference is required"):
        await service.add_evidence(
            actor_user_id=user.id,
            review_case_id=case.id,
            evidence_type="KYC_DOCUMENT",
            reference="   ",
            evidence_metadata={},
        )

    audit_log_service.record_admin_action.assert_not_awaited()
