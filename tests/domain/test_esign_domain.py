import pytest

from app.domain.esign import (
    CUSTOMER_STATUS,
    ESIGN_TRANSITIONS,
    ESignStatus,
    can_transition,
)


def test_every_status_has_transitions_and_customer_label():
    assert set(ESIGN_TRANSITIONS) == set(ESignStatus) == set(CUSTOMER_STATUS)


@pytest.mark.parametrize("final", [ESignStatus.SIGNED, ESignStatus.MANUAL_REVIEW])
def test_final_states_have_no_exits(final):
    assert all(not can_transition(final, s) for s in ESignStatus)


def test_signed_only_reachable_from_pending():
    sources = [s for s in ESignStatus if can_transition(s, ESignStatus.SIGNED)]
    assert sources == [ESignStatus.PENDING]


@pytest.mark.parametrize("dead", [ESignStatus.FAILED, ESignStatus.EXPIRED])
def test_dead_states_only_go_to_review(dead):
    assert [s for s in ESignStatus if can_transition(dead, s)] == [ESignStatus.MANUAL_REVIEW]


def test_customer_never_sees_internal_review_label():
    assert CUSTOMER_STATUS[ESignStatus.MANUAL_REVIEW] == "UNDER_REVIEW"
    assert CUSTOMER_STATUS[ESignStatus.INITIATED] == "PENDING"
