from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.loan_application import LoanApplication
from app.models.underwriting_review_case import UnderwritingReviewCase
from app.models.underwriting_override import UnderwritingOverride
from app.repositories.underwriting_override import UnderwritingOverrideRepository


async def create_review_case(db_session, user):
    application = LoanApplication(
        user_id=user.id,
        application_number=f"TEST-{uuid4().hex[:12].upper()}",
        status="SUBMITTED",
        requested_amount=Decimal("10000.00"),
        requested_tenure_days=30,
    )

    db_session.add(application)
    await db_session.flush()

    case = UnderwritingReviewCase(
        loan_application_id=application.id,
        user_id=user.id,
        status="QUEUED",
    )

    db_session.add(case)
    await db_session.flush()

    return case


@pytest.mark.asyncio
async def test_create_override(db_session, admin_user, user):
    review_case = await create_review_case(db_session, user)

    repository = UnderwritingOverrideRepository(db_session)

    override = await repository.create(
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="AMOUNT",
        original_value={"amount": "10000.00"},
        requested_value={"amount": "15000.00"},
        reason="Verified additional income supports the requested amount.",
    )

    assert override.id is not None
    assert override.review_case_id == review_case.id
    assert override.requested_by_admin_user_id == admin_user.id
    assert override.override_type == "AMOUNT"
    assert override.original_value == {"amount": "10000.00"}
    assert override.requested_value == {"amount": "15000.00"}
    assert override.reason.startswith("Verified")
    assert override.status == "REQUESTED"


@pytest.mark.asyncio
async def test_get_override_by_id(db_session, admin_user, user):
    review_case = await create_review_case(db_session, user)

    repository = UnderwritingOverrideRepository(db_session)

    created = await repository.create(
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="TENURE",
        original_value={"tenure_days": 30},
        requested_value={"tenure_days": 45},
        reason="Documented underwriting exception.",
    )

    fetched = await repository.get_by_id(
        override_id=created.id,
    )

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.override_type == "TENURE"


@pytest.mark.asyncio
async def test_list_overrides_by_review_case(
    db_session,
    admin_user,
    user,
):
    review_case = await create_review_case(db_session, user)

    repository = UnderwritingOverrideRepository(db_session)

    first = await repository.create(
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="AMOUNT",
        original_value={"amount": "10000.00"},
        requested_value={"amount": "12000.00"},
        reason="First documented exception.",
    )

    second = await repository.create(
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="TENURE",
        original_value={"tenure_days": 30},
        requested_value={"tenure_days": 45},
        reason="Second documented exception.",
    )

    results = await repository.list_by_review_case(
        review_case_id=review_case.id,
    )

    assert [item.id for item in results] == [
        first.id,
        second.id,
    ]


@pytest.mark.asyncio
async def test_list_overrides_by_status(
    db_session,
    admin_user,
    user,
):
    review_case = await create_review_case(db_session, user)

    repository = UnderwritingOverrideRepository(db_session)

    requested = await repository.create(
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="AMOUNT",
        original_value={"amount": "10000.00"},
        requested_value={"amount": "12000.00"},
        reason="Requested exception.",
    )

    approved = UnderwritingOverride(
        id=uuid4(),
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="RATE",
        original_value={"rate": "24.00"},
        requested_value={"rate": "22.00"},
        reason="Approved pricing exception.",
        status="APPROVED",
        approved_by_admin_user_id=admin_user.id,
    )

    db_session.add(approved)
    await db_session.flush()

    results = await repository.list_by_status(
        status="REQUESTED",
    )

    assert requested.id in [item.id for item in results]
    assert approved.id not in [item.id for item in results]


@pytest.mark.asyncio
async def test_multiple_overrides_are_scoped_to_review_case(
    db_session,
    admin_user,
    user,
):
    review_case = await create_review_case(db_session, user)
    other_case = await create_review_case(db_session, user)

    repository = UnderwritingOverrideRepository(db_session)

    first = await repository.create(
        review_case_id=review_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="AMOUNT",
        original_value={"amount": "10000.00"},
        requested_value={"amount": "12000.00"},
        reason="Primary case exception.",
    )

    second = await repository.create(
        review_case_id=other_case.id,
        requested_by_admin_user_id=admin_user.id,
        override_type="AMOUNT",
        original_value={"amount": "10000.00"},
        requested_value={"amount": "11000.00"},
        reason="Other case exception.",
    )

    results = await repository.list_by_review_case(
        review_case_id=review_case.id,
    )

    assert [item.id for item in results] == [first.id]
    assert second.id not in [item.id for item in results]