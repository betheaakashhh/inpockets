from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.loan_application import LoanApplication
from app.models.underwriting_review_case import UnderwritingReviewCase
from app.repositories.underwriting_review_evidence import (
    UnderwritingReviewEvidenceRepository,
)


async def create_review_case(db_session, user, admin_user=None):
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

    case = UnderwritingReviewCase(
        id=uuid4(),
        loan_application_id=application.id,
        user_id=user.id,
        status="QUEUED",
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.refresh(case)

    return case


@pytest.mark.asyncio
async def test_create_and_get_review_evidence(
    db_session,
    user,
    admin_user,
):
    case = await create_review_case(
        db_session,
        user,
        admin_user,
    )

    repository = UnderwritingReviewEvidenceRepository(db_session)

    evidence = await repository.create(
        review_case_id=case.id,
        added_by_admin_user_id=admin_user.id,
        evidence_type="KYC_DOCUMENT",
        reference="document:123",
        evidence_metadata={
            "document_type": "PAN",
            "source": "internal",
        },
    )

    fetched = await repository.get_by_id(
        evidence_id=evidence.id,
    )

    assert fetched is not None
    assert fetched.id == evidence.id
    assert fetched.review_case_id == case.id
    assert fetched.added_by_admin_user_id == admin_user.id
    assert fetched.evidence_type == "KYC_DOCUMENT"
    assert fetched.reference == "document:123"
    assert fetched.evidence_metadata == {
        "document_type": "PAN",
        "source": "internal",
    }


@pytest.mark.asyncio
async def test_list_evidence_by_review_case(
    db_session,
    user,
    admin_user,
):
    case = await create_review_case(
        db_session,
        user,
        admin_user,
    )

    repository = UnderwritingReviewEvidenceRepository(db_session)

    first = await repository.create(
        review_case_id=case.id,
        added_by_admin_user_id=admin_user.id,
        evidence_type="KYC_DOCUMENT",
        reference="document:1",
        evidence_metadata={"type": "PAN"},
    )

    second = await repository.create(
        review_case_id=case.id,
        added_by_admin_user_id=admin_user.id,
        evidence_type="BANK_STATEMENT",
        reference="document:2",
        evidence_metadata={"months": 6},
    )

    evidence = await repository.list_by_review_case(
        review_case_id=case.id,
    )

    assert {item.id for item in evidence} == {
        first.id,
        second.id,
    }

    assert [item.reference for item in evidence] == [
        "document:1",
        "document:2",
    ]


@pytest.mark.asyncio
async def test_get_missing_review_evidence_returns_none(
    db_session,
):
    repository = UnderwritingReviewEvidenceRepository(db_session)

    result = await repository.get_by_id(
        evidence_id=uuid4(),
    )

    assert result is None
