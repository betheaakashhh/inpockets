import uuid
import pytest
from datetime import datetime, timedelta, timezone
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services.otp as otp_service
from app.db.session import get_db_session
from app.main import app
from app.models.otp_verification import OTPVerification
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.user import UserRepository
from app.services.session import hash_token
from app.services.user import UserStatusService
from unittest.mock import patch


client = TestClient(app)


def request_otp_for_test(
    phone_number: str,
    monkeypatch,
    otp: str = "123456",
) -> None:
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


def test_request_otp() -> None:
    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "9876543210"},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "OTP sent successfully"
    assert "otp" not in data


def test_request_otp_rejects_invalid_phone() -> None:
    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": "12345"},
    )

    assert response.status_code == 422


def test_verify_otp(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543210",
        monkeypatch,
        otp,
    )

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543210",
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


def test_verify_otp_rejects_invalid_otp(monkeypatch) -> None:
    valid_otp = "123456"

    request_otp_for_test(
        "9876543212",
        monkeypatch,
        valid_otp,
    )

    invalid_otp = "999999"

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


def test_authenticated_user_can_access_me(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543213",
        monkeypatch,
        otp,
    )

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


def test_refresh_token(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543214",
        monkeypatch,
        otp,
    )

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


def test_logout_revokes_session(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543215",
        monkeypatch,
        otp,
    )

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


def test_revoked_access_token_cannot_access_me(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543216",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543216",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
    )

    assert logout_response.status_code == 200

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Session has been revoked"


def test_expired_access_token_cannot_access_me(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543217",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543217",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]

    async def expire_session() -> None:
        async for session in get_db_session():
            result = await session.execute(
                select(UserSession).where(
                    UserSession.access_token_hash.is_not(None)
                )
            )

            user_session = result.scalars().all()[-1]

            user_session.access_token_expires_at = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            )

            await session.commit()
            break

    asyncio.run(expire_session())

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Access token has expired"


def test_old_refresh_token_cannot_be_reused_after_rotation(
    monkeypatch,
) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543218",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543218",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    original_refresh_token = verify_response.json()["refresh_token"]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": original_refresh_token,
        },
    )

    assert refresh_response.status_code == 200

    new_refresh_token = refresh_response.json()["refresh_token"]

    assert new_refresh_token != original_refresh_token

    reuse_response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": original_refresh_token,
        },
    )

    assert reuse_response.status_code == 401


def test_expired_refresh_token_cannot_be_used(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543219",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543219",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    refresh_token = verify_response.json()["refresh_token"]

    async def expire_refresh_token() -> None:
        async for session in get_db_session():
            result = await session.execute(
                select(UserSession).where(
                    UserSession.refresh_token_hash
                    == hash_token(refresh_token)
                )
            )

            user_session = result.scalar_one()

            user_session.refresh_token_expires_at = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            )

            await session.commit()
            break

    asyncio.run(expire_refresh_token())

    response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Refresh token has expired"


def test_otp_attempt_limit(monkeypatch) -> None:
    otp = "123456"
    invalid_otp = "999999"

    request_otp_for_test(
        "9876543220",
        monkeypatch,
        otp,
    )

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/verify-otp",
            json={
                "phone_number": "9876543220",
                "otp": invalid_otp,
            },
        )

        assert response.status_code == 400

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543220",
            "otp": otp,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Invalid or expired OTP"


def test_expired_otp_cannot_be_used(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543221",
        monkeypatch,
        otp,
    )

    async def expire_otp() -> None:
        async for session in get_db_session():
            result = await session.execute(
                select(OTPVerification)
                .where(
                    OTPVerification.phone_number == "9876543221",
                    OTPVerification.purpose == "login",
                )
                .order_by(OTPVerification.created_at.desc())
                .limit(1)
            )

            otp_record = result.scalar_one()

            otp_record.expires_at = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            )

            await session.commit()
            break

    asyncio.run(expire_otp())

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543221",
            "otp": otp,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Invalid or expired OTP"


def test_verified_otp_cannot_be_reused(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543222",
        monkeypatch,
        otp,
    )

    first_verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543222",
            "otp": otp,
        },
    )

    assert first_verify_response.status_code == 200

    second_verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543222",
            "otp": otp,
        },
    )

    assert second_verify_response.status_code == 400
    assert second_verify_response.json()["error"]["message"] == "Invalid or expired OTP"


def test_newest_otp_replaces_previous_otp(monkeypatch) -> None:
    phone_number = "9876543231"

    monkeypatch.setattr(
        otp_service.settings,
        "otp_resend_cooldown_seconds",
        0,
    )

    otps = iter(["123456", "654321"])

    monkeypatch.setattr(
        otp_service,
        "generate_otp",
        lambda: next(otps),
    )

    first_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert first_response.status_code == 200

    second_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert second_response.status_code == 200

    verify_old_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": "123456",
        },
    )

    assert verify_old_response.status_code == 400

    verify_new_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": "654321",
        },
    )

    assert verify_new_response.status_code == 200


def test_inactive_user_cannot_access_me(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543224",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543224",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]
    user_id = verify_response.json()["user_id"]

    async def deactivate_user() -> None:
        async for session in get_db_session():
            result = await session.execute(
                select(User).where(User.id == user_id)
            )

            user = result.scalar_one()
            user.status = "inactive"

            await session.commit()
            break

    asyncio.run(deactivate_user())

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "User account is not active"


def test_user_status_can_be_changed(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543225",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543225",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    user_id = verify_response.json()["user_id"]

    async def update_user_status() -> None:
        async for session in get_db_session():
            result = await session.execute(
                select(User).where(User.id == user_id)
            )

            user = result.scalar_one()

            repository = UserRepository(session)
            service = UserStatusService(repository)

            updated_user = await service.update_status(
                user,
                new_status="blocked",
            )

            await session.commit()

            assert updated_user.status == "blocked"
            break

    asyncio.run(update_user_status())


def test_invalid_user_status_is_rejected(monkeypatch) -> None:
    otp = "123456"

    request_otp_for_test(
        "9876543226",
        monkeypatch,
        otp,
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543226",
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    user_id = verify_response.json()["user_id"]

    async def reject_invalid_status() -> None:
        async for session in get_db_session():
            result = await session.execute(
                select(User).where(User.id == user_id)
            )

            user = result.scalar_one()

            repository = UserRepository(session)
            service = UserStatusService(repository)

            try:
                await service.update_status(
                    user,
                    new_status="deleted",
                )

                assert False, "Expected ValueError"

            except ValueError as exc:
                assert str(exc) == "Invalid user status"

            break

    asyncio.run(reject_invalid_status())

def test_request_otp_resend_is_rate_limited(monkeypatch) -> None:
    phone_number = "9876543230"

    request_otp_for_test(
        phone_number,
        monkeypatch,
        "123456",
    )

    second_response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert second_response.status_code == 429

    data = second_response.json()

    assert "error" in data
    assert "OTP resend available in" in data["error"]["message"]

def test_request_otp_rate_limit(monkeypatch) -> None:
    phone_number = "9876500001"

    monkeypatch.setattr(
        otp_service.settings,
        "otp_resend_cooldown_seconds",
        0,
    )

    for _ in range(5):
        request_otp_for_test(
            phone_number,
            monkeypatch,
        )

    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert response.status_code == 429
    assert response.json()["error"]["message"] == (
        "Too many OTP requests. Please try again later."
    )
def test_request_otp_sends_sms(
    monkeypatch,
) -> None:
    phone_number = "9876543210"
    expected_otp = "123456"

    sent_sms: dict[str, str] = {}

    monkeypatch.setattr(
        otp_service,
        "generate_otp",
        lambda: expected_otp,
    )

    async def fake_send_otp(
        *,
        phone_number: str,
        otp: str,
    ) -> None:
        sent_sms["phone_number"] = phone_number
        sent_sms["otp"] = otp

    monkeypatch.setattr(
        otp_service.sms_service,
        "send_otp",
        fake_send_otp,
    )

    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "OTP sent successfully",
    }

    assert sent_sms == {
        "phone_number": phone_number,
        "otp": expected_otp,
    }

def test_refresh_token_reuse_revokes_token_family() -> None:
    phone_number = "9876543211"

    # Request OTP
    response = client.post(
        "/api/v1/auth/request-otp",
        json={"phone_number": phone_number},
    )
    assert response.status_code == 200

    # Get the OTP from the database/test setup in the same way
    # your existing refresh-token tests do.

def test_get_sessions_returns_user_sessions(monkeypatch) -> None:
    phone_number = "9876543232"
    otp = "123456"

    request_otp_for_test(phone_number, monkeypatch, otp)

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]

    response = client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200

    data = response.json()

    assert "sessions" in data
    assert len(data["sessions"]) == 1

    session_data = data["sessions"][0]

    assert "id" in session_data
    assert session_data["device_name"] is None
    assert session_data["device_type"] is None
    assert "created_at" in session_data
    assert "last_used_at" in session_data
    assert "access_token" not in session_data
    assert "refresh_token" not in session_data


def test_revoke_session(monkeypatch) -> None:
    phone_number = "9876543233"
    otp = "123456"

    request_otp_for_test(phone_number, monkeypatch, otp)

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": otp,
        },
    )

    assert verify_response.status_code == 200

    access_token = verify_response.json()["access_token"]

    sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert sessions_response.status_code == 200

    session_id = sessions_response.json()["sessions"][0]["id"]

    response = client.delete(
        f"/api/v1/auth/sessions/{session_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Session revoked successfully"

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert me_response.status_code == 401


def test_revoke_other_sessions(monkeypatch) -> None:
    phone_number = "9876543234"

    monkeypatch.setattr(
        otp_service.settings,
        "otp_resend_cooldown_seconds",
        0,
    )

    first_otp = "123456"

    request_otp_for_test(
        phone_number,
        monkeypatch,
        first_otp,
    )

    first_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": first_otp,
        },
    )

    assert first_response.status_code == 200

    first_access_token = first_response.json()["access_token"]

    second_otp = "654321"

    request_otp_for_test(
        phone_number,
        monkeypatch,
        second_otp,
    )

    second_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": second_otp,
        },
    )

    assert second_response.status_code == 200

    second_access_token = second_response.json()["access_token"]

    response = client.delete(
        "/api/v1/auth/sessions/others",
        headers={"Authorization": f"Bearer {second_access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["revoked_count"] == 1

    current_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {second_access_token}"},
    )

    assert current_response.status_code == 200

    previous_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first_access_token}"},
    )

    assert previous_response.status_code == 401


def test_revoke_session_not_owned_by_user(monkeypatch) -> None:
    phone_number_1 = "9876543235"
    phone_number_2 = "9876543236"

    request_otp_for_test(
        phone_number_1,
        monkeypatch,
        "123456",
    )

    response_1 = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number_1,
            "otp": "123456",
        },
    )

    assert response_1.status_code == 200

    token_1 = response_1.json()["access_token"]

    request_otp_for_test(
        phone_number_2,
        monkeypatch,
        "654321",
    )

    response_2 = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number_2,
            "otp": "654321",
        },
    )

    assert response_2.status_code == 200

    token_2 = response_2.json()["access_token"]

    sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {token_2}"},
    )

    assert sessions_response.status_code == 200

    session_id = sessions_response.json()["sessions"][0]["id"]

    response = client.delete(
        f"/api/v1/auth/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token_1}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Session not found"

def test_verify_otp_endpoint_rate_limit(monkeypatch) -> None:
    phone_number = f"987{uuid.uuid4().int % 10_000_000:07d}"
    otp = "123456"

    monkeypatch.setattr(
        otp_service.settings,
        "otp_verify_limit",
        2,
    )

    request_otp_for_test(
        phone_number,
        monkeypatch,
        otp,
    )

    for _ in range(2):
        response = client.post(
            "/api/v1/auth/verify-otp",
            json={
                "phone_number": phone_number,
                "otp": "999999",
            },
        )
        assert response.status_code == 400

    response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": "999999",
        },
    )

    assert response.status_code == 429
    assert response.json()["error"]["message"] == (
        "Too many OTP verification attempts. Please try again later."
    )
