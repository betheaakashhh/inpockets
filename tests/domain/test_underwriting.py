from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.underwriting import (
    UnderwritingReviewCase,
    UnderwritingReviewStatus,
)


def make_case(
    *,
    status: UnderwritingReviewStatus = UnderwritingReviewStatus.QUEUED,
    closed_at: datetime | None = None,
) -> UnderwritingReviewCase:
    return UnderwritingReviewCase(
        id=uuid4(),
        loan_application_id=uuid4(),
        user_id=uuid4(),
        status=status,
        closed_at=closed_at,
    )


def test_review_case_defaults_to_queued() -> None:
    case = make_case()

    assert case.status == UnderwritingReviewStatus.QUEUED
    assert case.is_open is True
    assert case.requires_human_decision is True
    assert case.is_terminal is False


@pytest.mark.parametrize(
    "status",
    [
        UnderwritingReviewStatus.ASSIGNED,
        UnderwritingReviewStatus.IN_REVIEW,
    ],
)
def test_active_review_statuses_require_human_decision(
    status: UnderwritingReviewStatus,
) -> None:
    case = make_case(status=status)

    assert case.is_open is True
    assert case.requires_human_decision is True
    assert case.is_terminal is False


@pytest.mark.parametrize(
    "status",
    [
        UnderwritingReviewStatus.APPROVED,
        UnderwritingReviewStatus.REJECTED,
        UnderwritingReviewStatus.CLOSED,
    ],
)
def test_terminal_review_statuses_require_closed_at(
    status: UnderwritingReviewStatus,
) -> None:
    closed_at = datetime.now(timezone.utc)

    case = make_case(
        status=status,
        closed_at=closed_at,
    )

    assert case.is_open is False
    assert case.requires_human_decision is False
    assert case.is_terminal is True
    assert case.closed_at == closed_at


@pytest.mark.parametrize(
    "status",
    [
        UnderwritingReviewStatus.APPROVED,
        UnderwritingReviewStatus.REJECTED,
        UnderwritingReviewStatus.CLOSED,
    ],
)
def test_terminal_status_without_closed_at_is_rejected(
    status: UnderwritingReviewStatus,
) -> None:
    with pytest.raises(
        ValueError,
        match="closed_at is required",
    ):
        make_case(status=status)


@pytest.mark.parametrize(
    "status",
    [
        UnderwritingReviewStatus.QUEUED,
        UnderwritingReviewStatus.ASSIGNED,
        UnderwritingReviewStatus.IN_REVIEW,
    ],
)
def test_active_status_cannot_have_closed_at(
    status: UnderwritingReviewStatus,
) -> None:
    with pytest.raises(
        ValueError,
        match="closed_at must be empty",
    ):
        make_case(
            status=status,
            closed_at=datetime.now(timezone.utc),
        )


def test_missing_loan_application_id_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="loan_application_id is required",
    ):
        UnderwritingReviewCase(
            id=uuid4(),
            loan_application_id=None,  # type: ignore[arg-type]
            user_id=uuid4(),
        )


def test_missing_user_id_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="user_id is required",
    ):
        UnderwritingReviewCase(
            id=uuid4(),
            loan_application_id=uuid4(),
            user_id=None,  # type: ignore[arg-type]
        )


def test_review_case_can_reference_decision_and_assigned_admin() -> None:
    decision_id = uuid4()
    admin_user_id = uuid4()

    case = UnderwritingReviewCase(
        id=uuid4(),
        loan_application_id=uuid4(),
        user_id=uuid4(),
        status=UnderwritingReviewStatus.ASSIGNED,
        loan_decision_id=decision_id,
        assigned_admin_user_id=admin_user_id,
    )

    assert case.loan_decision_id == decision_id
    assert case.assigned_admin_user_id == admin_user_id
    assert case.is_open is True