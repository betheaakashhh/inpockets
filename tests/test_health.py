from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check_returns_200() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200


def test_health_check_returns_expected_body() -> None:
    response = client.get("/api/v1/health")

    assert response.json() == {"status": "ok"}


def test_request_id_is_propagated() -> None:
    request_id = "test-request-123"

    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_request_id_is_generated_when_missing() -> None:
    response = client.get("/api/v1/health")

    request_id = response.headers["X-Request-ID"]

    UUID(request_id)

    assert len(request_id) == 36