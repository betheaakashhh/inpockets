from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

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
    assert response.status_code == 200, response.text

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": otp,
        },
    )
    assert response.status_code == 200, response.text

    return response.json()["access_token"]


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}

def create_application(
    access_token: str,
    amount: str = "5000.00",
    tenure_days: int = 30,
) -> dict:
    response = client.post(
        "/api/v1/loan-applications",
        json={
            "requested_amount": amount,
            "requested_tenure_days": tenure_days,
        },
        headers=auth_headers(access_token),
    )

    assert response.status_code == 201, response.text
    return response.json()


def submit_application(
    access_token: str,
    application_id: str,
) -> dict:
    response = client.post(
        f"/api/v1/loan-applications/{application_id}/submit",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200, response.text
    return response.json()


async def configure_admin(
    admin_user,
    db_session,
    role: str,
) -> None:
    admin_user.role = role
    admin_user.is_active = True
    await db_session.commit()

@pytest.mark.asyncio
async def test_admin_loan_application_requires_authentication():
    response = client.get(
        "/api/v1/admin/loan-applications",
        params={"user_id": uuid4()},
    )


    assert response.status_code == 401


@pytest.mark.asyncio
async def test_normal_customer_cannot_access_admin_loan_applications(
    monkeypatch,
):
    phone_number = f"987{uuid4().int % 10_000_000:07d}"


    access_token = authenticate_test_user(
        monkeypatch,
        phone_number,
    )

    response = client.get(
        "/api/v1/admin/loan-applications",
        params={"user_id": uuid4()},
        headers=auth_headers(access_token),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_read_only_admin_can_read_loan_application(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "READ_ONLY",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application = create_application(access_token)

    response = client.get(
        f"/api/v1/admin/loan-applications/{application['id']}",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200
    assert response.json()["id"] == application["id"]
    assert response.json()["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_read_only_admin_cannot_transition_loan_application(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "READ_ONLY",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application = create_application(access_token)
    submit_application(access_token, application["id"])

    response = client.post(
        f"/api/v1/admin/loan-applications/{application['id']}/process",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_underwriter_can_read_loan_application(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(admin_user, db_session, "UNDERWRITER")


    access_token = authenticate_test_user(monkeypatch, user.phone_number)

    application = create_application(access_token)

    response = client.get(
        f"/api/v1/admin/loan-applications/{application['id']}",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200
    assert response.json()["id"] == application["id"]


@pytest.mark.asyncio
async def test_underwriter_can_move_submitted_application_to_processing(
monkeypatch,
admin_user,
user,
db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "UNDERWRITER",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application = create_application(access_token)
    submit_application(access_token, application["id"])

    response = client.post(
        f"/api/v1/admin/loan-applications/{application['id']}/process",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == application["id"]
    assert body["status"] == "PROCESSING"


@pytest.mark.asyncio
async def test_admin_transition_rejects_invalid_transition(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "UNDERWRITER",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application = create_application(access_token)

    response = client.post(
        f"/api/v1/admin/loan-applications/{application['id']}/transition",
        json={
            "status": "APPROVED",
            "reason": "Attempted invalid direct approval.",
        },
        headers=auth_headers(access_token),
    )

    assert response.status_code == 400
    assert "Invalid loan application transition" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_transition_records_admin_actor(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "UNDERWRITER",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application = create_application(access_token)
    submit_application(access_token, application["id"])

    response = client.post(
        f"/api/v1/admin/loan-applications/{application['id']}/process",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200

    response = client.get(
        f"/api/v1/admin/loan-applications/{application['id']}/events",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200

    events = response.json()

    assert len(events) >= 3

    admin_event = events[-1]

    assert admin_event["event_type"] == "STATUS_CHANGED"
    assert admin_event["previous_status"] == "SUBMITTED"
    assert admin_event["new_status"] == "PROCESSING"
    assert admin_event["actor_type"] == "ADMIN"
    assert admin_event["actor_id"] == str(admin_user.id)


@pytest.mark.asyncio
async def test_admin_loan_application_returns_404_for_missing_application(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "UNDERWRITER",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application_id = uuid4()

    response = client.get(
        f"/api/v1/admin/loan-applications/{application_id}",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Loan application not found"


@pytest.mark.asyncio
async def test_admin_can_read_loan_application_events(
    monkeypatch,
    admin_user,
    user,
    db_session,
):
    await configure_admin(
        admin_user,
        db_session,
        "UNDERWRITER",
    )


    access_token = authenticate_test_user(
        monkeypatch,
        user.phone_number,
    )

    application = create_application(access_token)
    submit_application(access_token, application["id"])

    response = client.post(
        f"/api/v1/admin/loan-applications/{application['id']}/process",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200

    response = client.get(
        f"/api/v1/admin/loan-applications/{application['id']}/events",
        headers=auth_headers(access_token),
    )

    assert response.status_code == 200

    events = response.json()

    assert len(events) == 3

    assert events[0]["event_type"] == "APPLICATION_CREATED"
    assert events[1]["event_type"] == "APPLICATION_SUBMITTED"
    assert events[2]["event_type"] == "STATUS_CHANGED"
    assert events[2]["actor_type"] == "ADMIN"

