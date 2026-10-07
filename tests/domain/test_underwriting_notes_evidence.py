from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.underwriting import ReviewEvidence, ReviewNote


def test_review_note_requires_content():
    with pytest.raises(ValueError, match="content is required"):
        ReviewNote(
            id=uuid4(),
            review_case_id=uuid4(),
            author_admin_user_id=uuid4(),
            content="",
            created_at=datetime.now(timezone.utc),
        )


def test_review_note_is_immutable():
    note = ReviewNote(
        id=uuid4(),
        review_case_id=uuid4(),
        author_admin_user_id=uuid4(),
        content="Bank statement reviewed.",
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(Exception):
        note.content = "edited"


def test_review_evidence_requires_type():
    with pytest.raises(ValueError, match="evidence_type is required"):
        ReviewEvidence(
            id=uuid4(),
            review_case_id=uuid4(),
            added_by_admin_user_id=uuid4(),
            evidence_type="",
            reference="document:123",
            metadata={},
            created_at=datetime.now(timezone.utc),
        )


def test_review_evidence_requires_reference():
    with pytest.raises(ValueError, match="reference is required"):
        ReviewEvidence(
            id=uuid4(),
            review_case_id=uuid4(),
            added_by_admin_user_id=uuid4(),
            evidence_type="KYC_DOCUMENT",
            reference="",
            metadata={},
            created_at=datetime.now(timezone.utc),
        )


def test_review_evidence_is_immutable():
    evidence = ReviewEvidence(
        id=uuid4(),
        review_case_id=uuid4(),
        added_by_admin_user_id=uuid4(),
        evidence_type="KYC_DOCUMENT",
        reference="document:123",
        metadata={"document_type": "PAN"},
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(Exception):
        evidence.reference = "changed"