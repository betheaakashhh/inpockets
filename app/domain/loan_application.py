from enum import StrEnum


class LoanApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    PENDING_ADDITIONAL_INFORMATION = "PENDING_ADDITIONAL_INFORMATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


LOAN_APPLICATION_TRANSITIONS: dict[
    LoanApplicationStatus,
    frozenset[LoanApplicationStatus],
] = {
    LoanApplicationStatus.DRAFT: frozenset(
        {
            LoanApplicationStatus.SUBMITTED,
            LoanApplicationStatus.CANCELLED,
            LoanApplicationStatus.EXPIRED,
        }
    ),
    LoanApplicationStatus.SUBMITTED: frozenset(
        {
            LoanApplicationStatus.PROCESSING,
            LoanApplicationStatus.CANCELLED,
            LoanApplicationStatus.EXPIRED,
        }
    ),
    LoanApplicationStatus.PROCESSING: frozenset(
        {
            LoanApplicationStatus.PENDING_ADDITIONAL_INFORMATION,
            LoanApplicationStatus.MANUAL_REVIEW,
            LoanApplicationStatus.APPROVED,
            LoanApplicationStatus.REJECTED,
            LoanApplicationStatus.CANCELLED,
            LoanApplicationStatus.EXPIRED,
        }
    ),
    LoanApplicationStatus.PENDING_ADDITIONAL_INFORMATION: frozenset(
        {
            LoanApplicationStatus.PROCESSING,
            LoanApplicationStatus.CANCELLED,
            LoanApplicationStatus.EXPIRED,
        }
    ),
    LoanApplicationStatus.MANUAL_REVIEW: frozenset(
        {
            LoanApplicationStatus.APPROVED,
            LoanApplicationStatus.REJECTED,
            LoanApplicationStatus.CANCELLED,
            LoanApplicationStatus.EXPIRED,
        }
    ),
    LoanApplicationStatus.APPROVED: frozenset(),
    LoanApplicationStatus.REJECTED: frozenset(),
    LoanApplicationStatus.CANCELLED: frozenset(),
    LoanApplicationStatus.EXPIRED: frozenset(),
}


def is_valid_loan_application_transition(
    current_status: LoanApplicationStatus,
    next_status: LoanApplicationStatus,
) -> bool:
    """Return whether the requested status transition is allowed."""

    if current_status == next_status:
        return True

    return next_status in LOAN_APPLICATION_TRANSITIONS[current_status]