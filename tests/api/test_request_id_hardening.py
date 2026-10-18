from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_safe_client_request_id_is_echoed():
    r = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123_X.9"})
    assert r.headers["X-Request-ID"] == "abc-123_X.9"


def test_oversized_or_unsafe_request_ids_are_replaced():
    # These would overflow the audit_logs.request_id column or forge log lines.
    for bad in ["a" * 65, "has space", "semi;colon", "x\ty", "<script>"]:
        r = client.get("/api/v1/health", headers={"X-Request-ID": bad})
        assert r.headers["X-Request-ID"] != bad
        assert len(r.headers["X-Request-ID"]) == 36  # generated UUID
