from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.audit_log import _safe_snapshot

pytestmark = pytest.mark.unit


def test_audit_snapshot_redacts_sensitive_values_and_preserves_safe_metadata():
    snapshot = _safe_snapshot(
        {
            "pan": "ABCDE1234F",
            "phone_number": "9999999999",
            "bank_account": "1234567890",
            "nested": {"password": "secret", "status": "APPROVED"},
            "amount": Decimal("12.34"),
            "when": datetime(2026, 1, 1),
            "entity_id": uuid4(),
        }
    )

    assert snapshot["pan"] == "[REDACTED]"
    assert snapshot["phone_number"] == "[REDACTED]"
    assert snapshot["bank_account"] == "[REDACTED]"
    assert snapshot["nested"]["password"] == "[REDACTED]"
    assert snapshot["nested"]["status"] == "APPROVED"
    assert snapshot["amount"] == "12.34"
    assert snapshot["when"] == "2026-01-01T00:00:00"
    assert isinstance(snapshot["entity_id"], str)


def test_audit_snapshot_bounds_lists_and_long_strings():
    snapshot = _safe_snapshot({"items": list(range(150)), "message": "x" * 600})

    assert len(snapshot["items"]) == 100
    assert len(snapshot["message"]) == 500


def test_sensitive_entity_snapshot_allowlists_business_metadata():
    snapshot = _safe_snapshot(
        {
            "status": "VERIFIED",
            "reference": "provider-123",
            "amount": Decimal("10.00"),
            "name": "Customer Name",
            "nested": {"phone_number": "9999999999"},
        },
        entity_type="bank_verification",
    )

    assert snapshot["status"] == "VERIFIED"
    assert snapshot["reference"] == "provider-123"
    assert snapshot["amount"] == "10.00"
    assert snapshot["name"] == "[REDACTED]"
    assert snapshot["nested"] == "[REDACTED]"


def test_historical_snapshot_is_safe_when_read_back():
    snapshot = _safe_snapshot(
        {"legacy_field": "secret", "state": "APPROVED"},
        entity_type="customer_profile",
    )

    assert snapshot == {"legacy_field": "[REDACTED]", "state": "APPROVED"}
