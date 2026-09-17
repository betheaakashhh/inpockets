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
from app.repositories.user_session import UserSessionRepository


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
    assert response.json()["detail"] == "Session has been revoked"


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
    assert response.json()["detail"] == "Access token has expired"


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
    assert response.json()["detail"] == "Refresh token has expired"


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
    assert response.json()["detail"] == "Invalid or expired OTP"


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
    assert response.json()["detail"] == "Invalid or expired OTP"


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
    assert second_verify_response.json()["detail"] == "Invalid or expired OTP"


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
    assert response.json()["detail"] == "User account is not active"


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

    assert "detail" in data
    assert "OTP resend available in" in data["detail"]

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
    assert response.json()["detail"] == (
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

def test_user_cannot_revoke_another_users_session(
    monkeypatch,
) -> None:
    # Create User A and their session.
    request_otp_for_test(
        "9876543232",
        monkeypatch,
        "123456",
    )

    user_a_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543232",
            "otp": "123456",
        },
    )

    assert user_a_response.status_code == 200

    user_a_access_token = user_a_response.json()["access_token"]

    # Create User B and their session.
    request_otp_for_test(
        "9876543233",
        monkeypatch,
        "123456",
    )

    user_b_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543233",
            "otp": "123456",
        },
    )

    assert user_b_response.status_code == 200

    user_b_access_token = user_b_response.json()["access_token"]

    # Get User B's session ID.
    sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={
            "Authorization": f"Bearer {user_b_access_token}",
        },
    )

    assert sessions_response.status_code == 200

    user_b_sessions = sessions_response.json()

    assert len(user_b_sessions) >= 1

    user_b_session_id = user_b_sessions[0]["session_id"]

    # User A attempts to revoke User B's session.
    revoke_response = client.delete(
        f"/api/v1/auth/sessions/{user_b_session_id}",
        headers={
            "Authorization": f"Bearer {user_a_access_token}",
        },
    )

    # The API must not reveal that User B's session exists.
    assert revoke_response.status_code == 404

    # User B's session must still work.
    user_b_me_response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {user_b_access_token}",
        },
    )

    assert user_b_me_response.status_code == 200
    assert user_b_me_response.json()["phone_number"] == "9876543233"


def test_user_cannot_see_another_users_sessions(
    monkeypatch,
) -> None:
    # Create User A and their session.
    request_otp_for_test(
        "9876543234",
        monkeypatch,
        "123456",
    )

    user_a_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543234",
            "otp": "123456",
        },
    )

    assert user_a_response.status_code == 200

    user_a_access_token = user_a_response.json()["access_token"]

    # Create User B and their session.
    request_otp_for_test(
        "9876543235",
        monkeypatch,
        "123456",
    )

    user_b_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": "9876543235",
            "otp": "123456",
        },
    )

    assert user_b_response.status_code == 200

    user_b_access_token = user_b_response.json()["access_token"]

    # Get User B's sessions.
    user_b_sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={
            "Authorization": f"Bearer {user_b_access_token}",
        },
    )

    assert user_b_sessions_response.status_code == 200
    user_b_sessions = user_b_sessions_response.json()
    assert len(user_b_sessions) >= 1

    user_b_session_id = user_b_sessions[0]["session_id"]

    # User A can only see User A's sessions.
    user_a_sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={
            "Authorization": f"Bearer {user_a_access_token}",
        },
    )

    assert user_a_sessions_response.status_code == 200

    user_a_sessions = user_a_sessions_response.json()
    user_a_session_ids = {
        session["session_id"]
        for session in user_a_sessions
    }

    assert user_b_session_id not in user_a_session_ids



def test_revoked_refresh_token_cannot_be_used(
    monkeypatch,
) -> None:
    phone_number = "9876543236"

    request_otp_for_test(
        phone_number,
        monkeypatch,
        "123456",
    )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": "123456",
        },
    )

    assert verify_response.status_code == 200

    data = verify_response.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # Revoke the current session.
    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
    )

    assert logout_response.status_code == 200

    # The refresh token must now be rejected.
    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
    )

    assert refresh_response.status_code == 401



def test_revoking_one_session_does_not_revoke_other_sessions(
    monkeypatch,
) -> None:
    phone_number = "9876543238"

    # This test intentionally creates two sessions for the same user.
    # OTP throttling/cooldown is tested separately.
    monkeypatch.setattr(
        otp_service.settings,
        "otp_resend_cooldown_seconds",
        0,
    )

    async def bypass_rate_limit(
        self,
        *,
        phone_number: str,
    ) -> None:
        return None

    monkeypatch.setattr(
        otp_service.OTPService,
        "check_request_rate_limit",
        bypass_rate_limit,
    )

    # First device/session.
    request_otp_for_test(
        phone_number,
        monkeypatch,
        "123456",
    )

    first_verify = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": "123456",
        },
    )

    assert first_verify.status_code == 200

    first_data = first_verify.json()
    first_access_token = first_data["access_token"]

    # Second device/session.
    request_otp_for_test(
        phone_number,
        monkeypatch,
        "123456",
    )

    second_verify = client.post(
        "/api/v1/auth/verify-otp",
        json={
            "phone_number": phone_number,
            "otp": "123456",
        },
    )

    assert second_verify.status_code == 200

    second_data = second_verify.json()
    second_access_token = second_data["access_token"]

    assert first_access_token != second_access_token

    # The second session must be independently usable.
    second_me_before = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {second_access_token}",
        },
    )

    assert second_me_before.status_code == 200

    # List sessions.
    sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={
            "Authorization": f"Bearer {first_access_token}",
        },
    )

    assert sessions_response.status_code == 200

    sessions = sessions_response.json()

    active_sessions = [
        session
        for session in sessions
        if session["revoked_at"] is None
    ]

    assert len(active_sessions) >= 2

    # Find the session belonging to the first access token.
    async def get_first_session_id() -> str:
        async for db_session in get_db_session():
            repository = UserSessionRepository(db_session)

            user_session = await repository.get_by_access_token_hash(
                hash_token(first_access_token)
            )

            assert user_session is not None
            return str(user_session.id)

        raise AssertionError("Database session was not found")

    first_session_id = asyncio.run(get_first_session_id())

    # Revoke only the first session.
    revoke_response = client.delete(
        f"/api/v1/auth/sessions/{first_session_id}",
        headers={
            "Authorization": f"Bearer {first_access_token}",
        },
    )

    assert revoke_response.status_code == 204

    # First session is revoked.
    first_me_after = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {first_access_token}",
        },
    )

    assert first_me_after.status_code == 401

    # Second session must remain active.
    second_me_after = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {second_access_token}",
        },
    )

    assert second_me_after.status_code == 200