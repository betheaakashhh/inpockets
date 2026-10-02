from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.loan_application import LoanApplication
from app.models.underwriting_review_case import UnderwritingReviewCase
from app.repositories.underwriting_review_note import (
    UnderwritingReviewNoteRepository,
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
async def test_create_and_get_review_note(
    db_session,
    user,
    admin_user,
):
    case = await create_review_case(
        db_session,
        user,
        admin_user,
    )

    repository = UnderwritingReviewNoteRepository(db_session)

    note = await repository.create(
        review_case_id=case.id,
        author_admin_user_id=admin_user.id,
        content="Income documents reviewed.",
    )

    fetched = await repository.get_by_id(
        note_id=note.id,
    )

    assert fetched is not None
    assert fetched.id == note.id
    assert fetched.review_case_id == case.id
    assert fetched.author_admin_user_id == admin_user.id
    assert fetched.content == "Income documents reviewed."


@pytest.mark.asyncio
async def test_list_notes_by_review_case(
    db_session,
    user,
    admin_user,
):
    case = await create_review_case(
        db_session,
        user,
        admin_user,
    )

    repository = UnderwritingReviewNoteRepository(db_session)

    first = await repository.create(
        review_case_id=case.id,
        author_admin_user_id=admin_user.id,
        content="First note.",
    )

    second = await repository.create(
        review_case_id=case.id,
        author_admin_user_id=admin_user.id,
        content="Second note.",
    )

    notes = await repository.list_by_review_case(
        review_case_id=case.id,
    )

    assert {note.id for note in notes} == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_get_missing_review_note_returns_none(
    db_session,
):
    repository = UnderwritingReviewNoteRepository(db_session)

    result = await repository.get_by_id(
        note_id=uuid4(),
    )

    assert result is None
