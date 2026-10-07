from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.models.underwriting_review_case import UnderwritingReviewCase
from app.repositories.loan_application import LoanApplicationRepository
from app.repositories.underwriting_review_case import (
    UnderwritingReviewCaseRepository,
)


async def create_test_loan_application(db_session, user):
    repository = LoanApplicationRepository(db_session)
    return await repository.create(
        application_number=f"INP-UNDERWRITING-{uuid4().hex[:12]}",
        user_id=user.id,
        status="DRAFT",
        requested_amount=5000,
        requested_tenure_days=30,
    )


@pytest.mark.asyncio
async def test_create_and_get_review_case(db_session, user) -> None:
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )
    repository = UnderwritingReviewCaseRepository(db_session)
    case = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
    )

    assert case.id is not None
    assert case.status == "QUEUED"

    fetched = await repository.get_by_id(case.id)

    assert fetched is not None
    assert fetched.id == case.id
    assert fetched.loan_application_id == loan_application.id
    assert fetched.user_id == user.id


@pytest.mark.asyncio
async def test_get_cases_by_loan_application(db_session, user) -> None:
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )
    repository = UnderwritingReviewCaseRepository(db_session)

    first = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
    )
    second = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
    )

    cases = await repository.get_by_loan_application(
        loan_application.id
    )

    assert len(cases) == 2
    assert {case.id for case in cases} == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_list_by_status(db_session, user) -> None:
    queued_application = await create_test_loan_application(
        db_session,
        user,
    )
    review_application = await create_test_loan_application(
        db_session,
        user,
    )
    repository = UnderwritingReviewCaseRepository(db_session)

    queued = await repository.create(
        loan_application_id=queued_application.id,
        user_id=user.id,
        status="QUEUED",
    )
    await repository.create(
        loan_application_id=review_application.id,
        user_id=user.id,
        status="IN_REVIEW",
    )

    cases = await repository.list_by_status(status="QUEUED")

    assert len(cases) == 1
    assert cases[0].id == queued.id


@pytest.mark.asyncio
async def test_list_by_assigned_admin(db_session, user, admin_user) -> None:
    first_application = await create_test_loan_application(
        db_session,
        user,
    )
    second_application = await create_test_loan_application(
        db_session,
        user,
    )
    repository = UnderwritingReviewCaseRepository(db_session)

    assigned = await repository.create(
        loan_application_id=first_application.id,
        user_id=user.id,
        status="ASSIGNED",
        assigned_admin_user_id=admin_user.id,
    )
    await repository.create(
        loan_application_id=second_application.id,
        user_id=user.id,
        status="ASSIGNED",
    )

    cases = await repository.list_by_assigned_admin(
        admin_user_id=admin_user.id,
    )

    assert len(cases) == 1
    assert cases[0].id == assigned.id


@pytest.mark.asyncio
async def test_list_by_assigned_admin_can_filter_status(
    db_session,
    user,
    admin_user,
) -> None:
    first_application = await create_test_loan_application(
        db_session,
        user,
    )
    second_application = await create_test_loan_application(
        db_session,
        user,
    )
    repository = UnderwritingReviewCaseRepository(db_session)

    assigned = await repository.create(
        loan_application_id=first_application.id,
        user_id=user.id,
        status="ASSIGNED",
        assigned_admin_user_id=admin_user.id,
    )
    await repository.create(
        loan_application_id=second_application.id,
        user_id=user.id,
        status="IN_REVIEW",
        assigned_admin_user_id=admin_user.id,
    )

    cases = await repository.list_by_assigned_admin(
        admin_user_id=admin_user.id,
        status="ASSIGNED",
    )

    assert len(cases) == 1
    assert cases[0].id == assigned.id


@pytest.mark.asyncio
async def test_latest_review_case_for_application(
    db_session,
    user,
) -> None:
    loan_application = await create_test_loan_application(
        db_session,
        user,
    )
    repository = UnderwritingReviewCaseRepository(db_session)

    first = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
    )
    second = await repository.create(
        loan_application_id=loan_application.id,
        user_id=user.id,
    )

    # PostgreSQL's transaction-scoped now() can give multiple rows the
    # same created_at value. Set deterministic timestamps so this test
    # verifies the repository's "latest" ordering rather than insertion
    # timing or UUID ordering.
    base_time = datetime.now(timezone.utc)
    await db_session.execute(
        update(UnderwritingReviewCase)
        .where(UnderwritingReviewCase.id == first.id)
        .values(created_at=base_time)
    )
    await db_session.execute(
        update(UnderwritingReviewCase)
        .where(UnderwritingReviewCase.id == second.id)
        .values(created_at=base_time + timedelta(seconds=1))
    )
    await db_session.flush()

    latest = await repository.latest_for_loan_application(
        loan_application.id
    )

    assert latest is not None
    assert latest.id == second.id
    assert latest.id != first.id
