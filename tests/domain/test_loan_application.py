import pytest    ## type: ignore

from app.domain.loan_application import (
    LoanApplicationStatus,
    is_valid_loan_application_transition,
)


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (
            LoanApplicationStatus.DRAFT,
            LoanApplicationStatus.SUBMITTED,
        ),
        (
            LoanApplicationStatus.SUBMITTED,
            LoanApplicationStatus.PROCESSING,
        ),
        (
            LoanApplicationStatus.PROCESSING,
            LoanApplicationStatus.MANUAL_REVIEW,
        ),
        (
            LoanApplicationStatus.PROCESSING,
            LoanApplicationStatus.APPROVED,
        ),
        (
            LoanApplicationStatus.PROCESSING,
            LoanApplicationStatus.REJECTED,
        ),
        (
            LoanApplicationStatus.MANUAL_REVIEW,
            LoanApplicationStatus.APPROVED,
        ),
        (
            LoanApplicationStatus.MANUAL_REVIEW,
            LoanApplicationStatus.REJECTED,
        ),
        (
            LoanApplicationStatus.PENDING_ADDITIONAL_INFORMATION,
            LoanApplicationStatus.PROCESSING,
        ),
    ],
)
def test_valid_loan_application_transitions(current, next_status):
    assert is_valid_loan_application_transition(current, next_status)


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (
            LoanApplicationStatus.APPROVED,
            LoanApplicationStatus.PROCESSING,
        ),
        (
            LoanApplicationStatus.REJECTED,
            LoanApplicationStatus.APPROVED,
        ),
        (
            LoanApplicationStatus.CANCELLED,
            LoanApplicationStatus.SUBMITTED,
        ),
        (
            LoanApplicationStatus.EXPIRED,
            LoanApplicationStatus.PROCESSING,
        ),
        (
            LoanApplicationStatus.MANUAL_REVIEW,
            LoanApplicationStatus.PROCESSING,
        ),
    ],
)
def test_invalid_loan_application_transitions(current, next_status):
    assert not is_valid_loan_application_transition(current, next_status)


@pytest.mark.parametrize("status", LoanApplicationStatus)
def test_same_status_transition_is_allowed(status):
    assert is_valid_loan_application_transition(status, status)