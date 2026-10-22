import pytest

from app.domain.bank_verification import (
    CUSTOMER_STATUS,
    TRANSITIONS,
    BankVerificationStatus as S,
    can_transition,
    mask_account,
)


def test_all_statuses_covered():
    assert set(TRANSITIONS) == set(S) == set(CUSTOMER_STATUS)


@pytest.mark.parametrize("final", [S.VERIFIED, S.FAILED])
def test_final_states_have_no_exits(final):
    assert all(not can_transition(final, s) for s in S)


def test_manual_review_resolves_only_to_verified_or_failed():
    assert {s for s in S if can_transition(S.MANUAL_REVIEW, s)} == {S.VERIFIED, S.FAILED}


def test_verified_not_reachable_from_failed():
    assert not can_transition(S.FAILED, S.VERIFIED)


def test_customer_labels_hide_internal_states():
    assert CUSTOMER_STATUS[S.MANUAL_REVIEW] == "UNDER_REVIEW"
    assert CUSTOMER_STATUS[S.INITIATED] == "PENDING"


def test_mask_is_fixed_length():
    assert mask_account("1234") == "XXXXXXXX1234"
