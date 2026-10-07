from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class UnderwritingReviewStatus(StrEnum):
    """Lifecycle states for a manual underwriting review case."""

    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class UnderwritingReviewCase:
    """
    Domain contract for a lender-admin underwriting review case.

    A review case represents work that requires human underwriting review.
    It does not perform approval or disbursement itself.
    """

    id: UUID
    loan_application_id: UUID
    user_id: UUID
    status: UnderwritingReviewStatus = UnderwritingReviewStatus.QUEUED
    loan_decision_id: UUID | None = None
    assigned_admin_user_id: UUID | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is None:
            raise ValueError("id is required")

        if self.loan_application_id is None:
            raise ValueError("loan_application_id is required")

        if self.user_id is None:
            raise ValueError("user_id is required")

        if not isinstance(self.status, UnderwritingReviewStatus):
            raise ValueError("status must be a valid UnderwritingReviewStatus")

        if self.status in {
            UnderwritingReviewStatus.APPROVED,
            UnderwritingReviewStatus.REJECTED,
            UnderwritingReviewStatus.CLOSED,
        } and self.closed_at is None:
            raise ValueError(
                "closed_at is required for completed underwriting review cases"
            )

        if self.status in {
            UnderwritingReviewStatus.QUEUED,
            UnderwritingReviewStatus.ASSIGNED,
            UnderwritingReviewStatus.IN_REVIEW,
        } and self.closed_at is not None:
            raise ValueError(
                "closed_at must be empty for active underwriting review cases"
            )

    @property
    def is_open(self) -> bool:
        """Whether the review case still requires active workflow handling."""

        return self.status in {
            UnderwritingReviewStatus.QUEUED,
            UnderwritingReviewStatus.ASSIGNED,
            UnderwritingReviewStatus.IN_REVIEW,
        }

    @property
    def requires_human_decision(self) -> bool:
        """Whether the case represents an active manual underwriting decision."""

        return self.is_open

    @property
    def is_terminal(self) -> bool:
        """Whether the review case has reached a terminal state."""

        return self.status in {
            UnderwritingReviewStatus.APPROVED,
            UnderwritingReviewStatus.REJECTED,
            UnderwritingReviewStatus.CLOSED,
        }

@dataclass(frozen=True)
class ReviewNote:
    id: UUID
    review_case_id: UUID
    author_admin_user_id: UUID
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.id is None:
            raise ValueError("id is required")
        if self.review_case_id is None:
            raise ValueError("review_case_id is required")
        if self.author_admin_user_id is None:
            raise ValueError("author_admin_user_id is required")
        if not self.content or not self.content.strip():
            raise ValueError("content is required")
        if self.created_at is None:
            raise ValueError("created_at is required")

@dataclass(frozen=True)
class ReviewEvidence:
    id: UUID
    review_case_id: UUID
    added_by_admin_user_id: UUID
    evidence_type: str
    reference: str
    metadata: dict[str, object]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.id is None:
            raise ValueError("id is required")
        if self.review_case_id is None:
            raise ValueError("review_case_id is required")
        if self.added_by_admin_user_id is None:
            raise ValueError("added_by_admin_user_id is required")
        if not self.evidence_type or not self.evidence_type.strip():
            raise ValueError("evidence_type is required")
        if not self.reference or not self.reference.strip():
            raise ValueError("reference is required")
        if self.metadata is None:
            raise ValueError("metadata is required")
        if self.created_at is None:
            raise ValueError("created_at is required")
        
class UnderwritingOverrideStatus(StrEnum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class UnderwritingOverride:
    id: UUID
    review_case_id: UUID
    requested_by_admin_user_id: UUID

    override_type: str
    original_value: dict[str, object]
    requested_value: dict[str, object]

    reason: str

    status: UnderwritingOverrideStatus = UnderwritingOverrideStatus.REQUESTED

    approved_by_admin_user_id: UUID | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None

    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is None:
            raise ValueError("override id is required")

        if self.review_case_id is None:
            raise ValueError("review_case_id is required")

        if self.requested_by_admin_user_id is None:
            raise ValueError("requested_by_admin_user_id is required")

        if not self.override_type.strip():
            raise ValueError("override_type is required")

        if not self.reason.strip():
            raise ValueError("override reason is required")

        if not self.original_value:
            raise ValueError("original_value is required")

        if not self.requested_value:
            raise ValueError("requested_value is required")

        if self.status == UnderwritingOverrideStatus.APPROVED:
            if self.approved_by_admin_user_id is None:
                raise ValueError(
                    "approved override requires an approver"
                )

            if self.approved_at is None:
                raise ValueError(
                    "approved override requires approved_at"
                )

        if self.status == UnderwritingOverrideStatus.REJECTED:
            if self.rejected_at is None:
                raise ValueError(
                    "rejected override requires rejected_at"
                )