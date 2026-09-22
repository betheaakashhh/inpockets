from fastapi.testclient import TestClient

import app.services.otp as otp_service
from app.main import app


client = TestClient(app)


def authenticate_test_user(
    monkeypatch,
    phone_number: str = "9876543001",
    otp: str = "123456",
) -> str:
    monkeypatch.setattr(
        otp_service,
        "generate_otp",
        lambda: otp,
    )

    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert response.status_code == 200

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": otp,
        },
    )

    assert response.status_code == 200

    return response.json()["access_token"]


def auth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
    }


def test_get_onboarding_requires_authentication() -> None:
    response = client.get("/api/v1/onboarding")

    assert response.status_code == 401


def test_get_onboarding_creates_record(monkeypatch) -> None:
    token = authenticate_test_user(monkeypatch)

    response = client.get(
        "/api/v1/onboarding",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert "id" in data
    assert data["status"] == "NOT_STARTED"
    assert data["current_step"] == "PROFILE"
    assert "created_at" in data
    assert "updated_at" in data


def test_get_onboarding_returns_existing_record(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543002",
    )

    first_response = client.get(
        "/api/v1/onboarding",
        headers=auth_headers(token),
    )

    second_response = client.get(
        "/api/v1/onboarding",
        headers=auth_headers(token),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_data = first_response.json()
    second_data = second_response.json()

    assert first_data["id"] == second_data["id"]


def test_get_profile_creates_profile(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543003",
    )

    response = client.get(
        "/api/v1/onboarding/profile",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert "id" in data
    assert data["first_name"] is None
    assert data["last_name"] is None
    assert data["date_of_birth"] is None
    assert data["gender"] is None
    assert "created_at" in data
    assert "updated_at" in data


def test_update_profile(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543004",
    )

    response = client.put(
        "/api/v1/onboarding/profile",
        headers=auth_headers(token),
        json={
            "first_name": "Aakash",
            "last_name": "Sahu",
            "date_of_birth": "2000-01-15",
            "gender": "male",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["first_name"] == "Aakash"
    assert data["last_name"] == "Sahu"
    assert data["date_of_birth"] == "2000-01-15"
    assert data["gender"] == "male"


def test_update_profile_can_be_partial(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543005",
    )

    first_response = client.put(
        "/api/v1/onboarding/profile",
        headers=auth_headers(token),
        json={
            "first_name": "Aakash",
            "last_name": "Sahu",
        },
    )

    assert first_response.status_code == 200

    second_response = client.put(
        "/api/v1/onboarding/profile",
        headers=auth_headers(token),
        json={
            "gender": "male",
        },
    )

    assert second_response.status_code == 200

    data = second_response.json()

    assert data["gender"] == "male"


def test_update_onboarding_step_to_pan(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543006",
    )

    response = client.patch(
        "/api/v1/onboarding",
        headers=auth_headers(token),
        json={
            "current_step": "PAN",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "IN_PROGRESS"
    assert data["current_step"] == "PAN"


def test_update_onboarding_step_rejects_skipping(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543007",
    )

    response = client.patch(
        "/api/v1/onboarding",
        headers=auth_headers(token),
        json={
            "current_step": "KYC",
        },
    )

    assert response.status_code == 400
    assert "Invalid onboarding step transition" in response.json()["error"]["message"]


def test_update_onboarding_step_rejects_backward_transition(
    monkeypatch,
) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543008",
    )

    response = client.patch(
        "/api/v1/onboarding",
        headers=auth_headers(token),
        json={
            "current_step": "PAN",
        },
    )

    assert response.status_code == 200

    response = client.patch(
        "/api/v1/onboarding",
        headers=auth_headers(token),
        json={
            "current_step": "PROFILE",
        },
    )

    assert response.status_code == 400
    assert "Invalid onboarding step transition" in response.json()["error"]["message"]


def test_update_onboarding_step_rejects_invalid_step(
    monkeypatch,
) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543009",
    )

    response = client.patch(
        "/api/v1/onboarding",
        headers=auth_headers(token),
        json={
            "current_step": "INVALID",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Invalid onboarding step"


def test_complete_onboarding(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543010",
    )
    headers = auth_headers(token)

    for step in ("PAN", "KYC", "IDENTITY", "COMPLETED"):
        response = client.patch(
            "/api/v1/onboarding",
            headers=headers,
            json={"current_step": step},
        )

        assert response.status_code == 200

    data = response.json()

    assert data["status"] == "COMPLETED"
    assert data["current_step"] == "COMPLETED"


def test_record_consent(monkeypatch) -> None:
    token = authenticate_test_user(
        monkeypatch,
        phone_number="9876543011",
    )

    response = client.post(
        "/api/v1/onboarding/consents",
        headers=auth_headers(token),
        json={
            "consent_type": "TERMS_AND_CONDITIONS",
            "version": "1.0",
            "status": "GRANTED",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert "id" in data
    assert data["consent_type"] == "TERMS_AND_CONDITIONS"
    assert data["version"] == "1.0"
    assert data["status"] == "GRANTED"
    assert "created_at" in data