import pytest

from app.domain.disbursement import (
    CUSTOMER_STATUS,
    LIVE_STATUSES,
    TRANSITIONS,
    DisbursementStatus as S,
    can_transition,
)


def test_every_status_covered():
    assert set(TRANSITIONS) == set(S) == set(CUSTOMER_STATUS)


def test_reversed_is_final():
    assert all(not can_transition(S.REVERSED, s) for s in S)


def test_success_can_only_be_reversed():
    assert {s for s in S if can_transition(S.SUCCESS, s)} == {S.REVERSED}


def test_success_never_reachable_from_failed_or_pending():
    assert not can_transition(S.FAILED, S.SUCCESS)
    assert not can_transition(S.PENDING, S.SUCCESS)


def test_a_late_success_after_failure_only_goes_to_review():
    assert {s for s in S if can_transition(S.FAILED, s)} == {S.REQUIRES_REVIEW}


def test_review_exits_only_to_success_or_failed():
    assert {s for s in S if can_transition(S.REQUIRES_REVIEW, s)} == {S.SUCCESS, S.FAILED}


@pytest.mark.parametrize("status", [S.PENDING, S.PROCESSING, S.REQUIRES_REVIEW])
def test_customers_never_see_internal_uncertainty(status):
    assert CUSTOMER_STATUS[status] == "PROCESSING"


def test_live_statuses_exclude_retryable_ones():
    assert S.FAILED not in LIVE_STATUSES and S.REVERSED not in LIVE_STATUSES
    assert S.SUCCESS in LIVE_STATUSES
