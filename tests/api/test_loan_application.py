from uuid import uuid4

import pytest #type: ignore
from fastapi.testclient import TestClient #type: ignore

import app.services.otp as otp_service
from app.main import app


client = TestClient(app)


def authenticate_test_user(
    monkeypatch,
    phone_number: str,
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


@pytest.mark.asyncio
async def test_create_loan_application_requires_authentication():
    response = client.post(
        "/api/v1/loan-applications",
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_loan_application_creates_draft(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert response.status_code == 201, response.json()

    data = response.json()

    assert data["application_number"].startswith("LA-")
    assert data["status"] == "DRAFT"
    assert data["requested_amount"] == "5000.00"
    assert data["requested_tenure_days"] == 30
    assert data["submitted_at"] is None
    assert "id" in data
    assert "user_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_list_loan_applications_returns_customer_applications(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
        json={
            "requested_amount": "7500.00",
            "requested_tenure_days": 45,
        },
    )

    assert create_response.status_code == 201

    response = client.get(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["status"] == "DRAFT"
    assert data[0]["requested_amount"] == "7500.00"
    assert data[0]["requested_tenure_days"] == 45


@pytest.mark.asyncio
async def test_get_loan_application_returns_customer_application(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
        json={
            "requested_amount": "10000.00",
            "requested_tenure_days": 60,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/loan-applications/{application_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == application_id
    assert data["status"] == "DRAFT"
    assert data["requested_amount"] == "10000.00"
    assert data["requested_tenure_days"] == 60


@pytest.mark.asyncio
async def test_get_loan_application_returns_404_for_missing_application(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.get(
        f"/api/v1/loan-applications/{uuid4()}",
        headers=auth_headers(token),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Loan application not found"


@pytest.mark.asyncio
async def test_customer_cannot_access_another_users_application(
    monkeypatch,
):
    first_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(first_token),
        json={
            "requested_amount": "9000.00",
            "requested_tenure_days": 30,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    second_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.get(
        f"/api/v1/loan-applications/{application_id}",
        headers=auth_headers(second_token),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Loan application not found"


@pytest.mark.asyncio
async def test_submit_loan_application(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    response = client.post(
        f"/api/v1/loan-applications/{application_id}/submit",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.json()

    data = response.json()

    assert data["id"] == application_id
    assert data["status"] == "SUBMITTED"
    assert data["submitted_at"] is not None


@pytest.mark.asyncio
async def test_submit_loan_application_is_idempotent(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    first_response = client.post(
        f"/api/v1/loan-applications/{application_id}/submit",
        headers=auth_headers(token),
    )

    assert first_response.status_code == 200

    second_response = client.post(
        f"/api/v1/loan-applications/{application_id}/submit",
        headers=auth_headers(token),
    )

    assert second_response.status_code == 200

    first_data = first_response.json()
    second_data = second_response.json()

    assert second_data["id"] == first_data["id"]
    assert second_data["status"] == "SUBMITTED"
    assert second_data["submitted_at"] == first_data["submitted_at"]


@pytest.mark.asyncio
async def test_submit_application_rejects_different_user(
    monkeypatch,
):
    first_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(first_token),
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    second_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.post(
        f"/api/v1/loan-applications/{application_id}/submit",
        headers=auth_headers(second_token),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Loan application not found"


@pytest.mark.asyncio
async def test_get_loan_application_events(
    monkeypatch,
):
    token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(token),
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    submit_response = client.post(
        f"/api/v1/loan-applications/{application_id}/submit",
        headers=auth_headers(token),
    )

    assert submit_response.status_code == 200

    response = client.get(
        f"/api/v1/loan-applications/{application_id}/events",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    events = response.json()

    assert len(events) == 2

    assert events[0]["event_type"] == "APPLICATION_CREATED"
    assert events[0]["previous_status"] is None
    assert events[0]["new_status"] == "DRAFT"

    assert events[1]["event_type"] == "APPLICATION_SUBMITTED"
    assert events[1]["previous_status"] == "DRAFT"
    assert events[1]["new_status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_get_events_rejects_different_user(
    monkeypatch,
):
    first_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    create_response = client.post(
        "/api/v1/loan-applications",
        headers=auth_headers(first_token),
        json={
            "requested_amount": "5000.00",
            "requested_tenure_days": 30,
        },
    )

    assert create_response.status_code == 201

    application_id = create_response.json()["id"]

    second_token = authenticate_test_user(
        monkeypatch,
        phone_number=f"987{uuid4().int % 10_000_000:07d}",
    )

    response = client.get(
        f"/api/v1/loan-applications/{application_id}/events",
        headers=auth_headers(second_token),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Loan application not found"