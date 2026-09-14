from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_request_otp() -> None:
    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543210"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "OTP generated successfully"
    assert "otp" in data
    assert len(data["otp"]) == 6
    assert data["otp"].isdigit()


def test_request_otp_rejects_invalid_phone() -> None:
    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "12345"},
    )

    assert response.status_code == 422


def test_verify_otp() -> None:
    request_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543211"},
    )

    assert request_response.status_code == 200

    otp = request_response.json()["otp"]

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543211",
            "otp": otp,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "OTP verified successfully"
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert "user_id" in data


def test_verify_otp_rejects_invalid_otp() -> None:
    request_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543212"},
    )

    assert request_response.status_code == 200

    valid_otp = request_response.json()["otp"]

    invalid_otp = "999999" if valid_otp != "999999" else "888888"

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543212",
            "otp": invalid_otp,
        },
    )

    assert response.status_code == 400


def test_me_requires_authentication() -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_authenticated_user_can_access_me() -> None:
    request_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543213"},
    )

    assert request_response.status_code == 200

    otp = request_response.json()["otp"]

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543213",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["phone_number"] == "9876543213"


def test_refresh_token() -> None:
    request_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543214"},
    )

    assert request_response.status_code == 200

    otp = request_response.json()["otp"]

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543214",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    original_refresh_token = verify_response.json()["refresh_token"]
    original_access_token = verify_response.json()["access_token"]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh_token},
    )

    assert refresh_response.status_code == 200

    data = refresh_response.json()

    assert data["message"] == "Token refreshed successfully"
    assert data["token_type"] == "bearer"
    assert data["access_token"] != original_access_token
    assert data["refresh_token"] != original_refresh_token


def test_refresh_token_rejects_invalid_token() -> None:
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-refresh-token"},
    )

    assert response.status_code == 401


def test_logout_revokes_session() -> None:
    request_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543215"},
    )

    assert request_response.status_code == 200

    otp = request_response.json()["otp"]

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543215",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert logout_response.status_code == 200

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert me_response.status_code == 401