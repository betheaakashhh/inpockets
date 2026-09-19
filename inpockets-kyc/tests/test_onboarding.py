from fastapi.testclient import TestClient

import app.services.otp as otp_service
from app.main import app

client = TestClient(app)


def _create_authenticated_user(
    phone_number: str,
    monkeypatch,
    otp: str = "123456",
) -> str:
    """Runs the OTP flow to get a real access token for a real user - the
    onboarding endpoints all require authentication, so every test here
    needs one. Mirrors request_otp_for_test in tests/test_auth.py.
    """
    monkeypatch.setattr(
        otp_service,
        "generate_otp",
        lambda: otp,
    )

    request_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )
    assert request_response.status_code == 200

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone_number": phone_number, "otp": otp},
    )
    assert verify_response.status_code == 200

    access_token: str = verify_response.json()["access_token"]
    return access_token


def test_onboarding_requires_authentication() -> None:
    response = client.post(
        "/api/v1/onboarding/pan",
        json={"pan_number": "ABCDE1234F", "full_name": "Test User"},
    )
    assert response.status_code == 401


def test_submit_pan_success(monkeypatch) -> None:
    token = _create_authenticated_user("9876540001", monkeypatch)

    response = client.post(
        "/api/v1/onboarding/pan",
        json={"pan_number": "ABCDE1234F", "full_name": "Test User"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "verified"
    assert data["verified_name"] == "Test User"


def test_submit_pan_rejects_invalid_format(monkeypatch) -> None:
    token = _create_authenticated_user("9876540002", monkeypatch)

    response = client.post(
        "/api/v1/onboarding/pan",
        json={"pan_number": "not-a-pan", "full_name": "Test User"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


def test_get_latest_pan_verification(monkeypatch) -> None:
    token = _create_authenticated_user("9876540003", monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/api/v1/onboarding/pan",
        json={"pan_number": "ABCDE1234F", "full_name": "Test User"},
        headers=headers,
    )

    response = client.get("/api/v1/onboarding/pan/latest", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def test_get_latest_pan_verification_404_when_none_exists(monkeypatch) -> None:
    token = _create_authenticated_user("9876540004", monkeypatch)

    response = client.get(
        "/api/v1/onboarding/pan/latest",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_kyc_initiate_and_poll_to_verified_retrieves_documents(monkeypatch) -> None:
    token = _create_authenticated_user("9876540005", monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}

    initiate_response = client.post("/api/v1/onboarding/kyc/initiate", headers=headers)
    assert initiate_response.status_code == 200
    initiate_data = initiate_response.json()
    assert initiate_data["status"] == "initiated"
    assert initiate_data["consent_url"]

    kyc_id = initiate_data["id"]

    status_response = client.get(f"/api/v1/onboarding/kyc/{kyc_id}", headers=headers)
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "verified"
    assert status_data["completed_at"] is not None
    # The mock provider's default outcome is "verified", which surfaces one
    # available document - proves the fetch-and-persist path actually ran,
    # not just that the status flipped.
    assert status_data["document_count"] == 1


def test_kyc_status_requires_ownership(monkeypatch) -> None:
    token_a = _create_authenticated_user("9876540006", monkeypatch, otp="111111")
    token_b = _create_authenticated_user("9876540007", monkeypatch, otp="222222")

    initiate_response = client.post(
        "/api/v1/onboarding/kyc/initiate",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    kyc_id = initiate_response.json()["id"]

    response = client.get(
        f"/api/v1/onboarding/kyc/{kyc_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert response.status_code == 404


def test_identity_verification_flow(monkeypatch) -> None:
    token = _create_authenticated_user("9876540008", monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}

    initiate_response = client.post(
        "/api/v1/onboarding/identity-verification/initiate", headers=headers
    )
    assert initiate_response.status_code == 200
    initiate_data = initiate_response.json()
    assert initiate_data["status"] == "pending"
    assert initiate_data["capture_session_token"]

    record_id = initiate_data["id"]

    submit_response = client.post(
        f"/api/v1/onboarding/identity-verification/{record_id}/submit",
        json={"capture_ref": "fake-capture-ref"},
        headers=headers,
    )

    assert submit_response.status_code == 200
    submit_data = submit_response.json()
    assert submit_data["status"] == "verified"
    assert submit_data["confidence_score"] is not None


def test_onboarding_status_aggregates_all_three_checks(monkeypatch) -> None:
    token = _create_authenticated_user("9876540009", monkeypatch)
    headers = {"Authorization": f"Bearer {token}"}

    before = client.get("/api/v1/onboarding/status", headers=headers)
    assert before.status_code == 200
    assert before.json()["onboarding_complete"] is False
    assert before.json()["pan_status"] is None

    client.post(
        "/api/v1/onboarding/pan",
        json={"pan_number": "ABCDE1234F", "full_name": "Test User"},
        headers=headers,
    )

    kyc_id = client.post("/api/v1/onboarding/kyc/initiate", headers=headers).json()["id"]
    client.get(f"/api/v1/onboarding/kyc/{kyc_id}", headers=headers)

    identity_id = client.post(
        "/api/v1/onboarding/identity-verification/initiate", headers=headers
    ).json()["id"]
    client.post(
        f"/api/v1/onboarding/identity-verification/{identity_id}/submit",
        json={"capture_ref": "fake-capture-ref"},
        headers=headers,
    )

    after = client.get("/api/v1/onboarding/status", headers=headers)
    assert after.status_code == 200
    data = after.json()
    assert data["pan_status"] == "verified"
    assert data["kyc_status"] == "verified"
    assert data["identity_verification_status"] == "verified"
    assert data["onboarding_complete"] is True
