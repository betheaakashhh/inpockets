from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.underwriting import (
    UnderwritingOverride,
    UnderwritingOverrideStatus,
)


def make_override(**overrides):
    values = {
        "id": uuid4(),
        "review_case_id": uuid4(),
        "requested_by_admin_user_id": uuid4(),
        "override_type": "LOAN_AMOUNT",
        "original_value": {
            "amount": "10000.00",
        },
        "requested_value": {
            "amount": "15000.00",
        },
        "reason": "Verified additional income documentation.",
        "created_at": datetime.now(timezone.utc),
    }

    values.update(overrides)
    return UnderwritingOverride(**values)


def test_override_defaults_to_requested():
    override = make_override()

    assert override.status == UnderwritingOverrideStatus.REQUESTED
    assert override.approved_by_admin_user_id is None
    assert override.approved_at is None
    assert override.rejected_at is None


def test_override_requires_reason():
    with pytest.raises(ValueError, match="override reason is required"):
        make_override(reason="   ")


def test_override_requires_type():
    with pytest.raises(ValueError, match="override_type is required"):
        make_override(override_type="   ")


def test_override_requires_original_value():
    with pytest.raises(ValueError, match="original_value is required"):
        make_override(original_value={})


def test_override_requires_requested_value():
    with pytest.raises(ValueError, match="requested_value is required"):
        make_override(requested_value={})


def test_approved_override_requires_approver():
    with pytest.raises(
        ValueError,
        match="approved override requires an approver",
    ):
        make_override(
            status=UnderwritingOverrideStatus.APPROVED,
            approved_at=datetime.now(timezone.utc),
        )


def test_approved_override_requires_approval_timestamp():
    with pytest.raises(
        ValueError,
        match="approved override requires approved_at",
    ):
        make_override(
            status=UnderwritingOverrideStatus.APPROVED,
            approved_by_admin_user_id=uuid4(),
        )


def test_valid_approved_override():
    approver_id = uuid4()
    approved_at = datetime.now(timezone.utc)

    override = make_override(
        status=UnderwritingOverrideStatus.APPROVED,
        approved_by_admin_user_id=approver_id,
        approved_at=approved_at,
    )

    assert override.status == UnderwritingOverrideStatus.APPROVED
    assert override.approved_by_admin_user_id == approver_id
    assert override.approved_at == approved_at


def test_valid_rejected_override():
    rejected_at = datetime.now(timezone.utc)

    override = make_override(
        status=UnderwritingOverrideStatus.REJECTED,
        rejected_at=rejected_at,
    )

    assert override.status == UnderwritingOverrideStatus.REJECTED
    assert override.rejected_at == rejected_at