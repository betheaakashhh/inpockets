import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.api.test_loan_offer_api import make_actor

client = TestClient(app)


async def test_user_limit_returns_429_with_retry_after(monkeypatch, db_session):
    _, headers = await make_actor(monkeypatch, db_session)
    monkeypatch.setattr(get_settings(), "rate_limit_user_per_minute", 3)
    statuses = [client.get("/api/v1/loan-offers", headers=headers) for _ in range(5)]
    assert [r.status_code for r in statuses[:3]] == [200, 200, 200]
    assert statuses[3].status_code == 429 and statuses[4].status_code == 429
    assert int(statuses[3].headers["Retry-After"]) >= 1


async def test_limits_are_per_user(monkeypatch, db_session):
    _, first = await make_actor(monkeypatch, db_session)
    _, second = await make_actor(monkeypatch, db_session)
    monkeypatch.setattr(get_settings(), "rate_limit_user_per_minute", 2)
    for _ in range(3):
        client.get("/api/v1/loan-offers", headers=first)
    assert client.get("/api/v1/loan-offers", headers=first).status_code == 429
    assert client.get("/api/v1/loan-offers", headers=second).status_code == 200


async def test_sensitive_budget_is_stricter(monkeypatch, db_session):
    _, headers = await make_actor(monkeypatch, db_session)
    monkeypatch.setattr(get_settings(), "rate_limit_sensitive_per_minute", 2)
    codes = [
        client.post(
            "/api/v1/bank-verifications",
            json={"account_number": "123456789012", "ifsc": "HDFC0001234"},
            headers=headers,
        ).status_code
        for _ in range(3)
    ]
    assert codes[2] == 429 and 429 not in codes[:2]


async def test_unauthenticated_requests_are_not_counted_as_a_user(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_user_per_minute", 1)
    assert client.get("/api/v1/loan-offers").status_code in (401, 403)


async def test_webhook_limit_is_per_ip(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_webhook_per_minute", 2)
    codes = [
        client.post("/api/v1/webhooks/esign/development", content=b"{}").status_code
        for _ in range(3)
    ]
    assert codes[2] == 429 and 429 not in codes[:2]


async def test_disabled_limiter_never_blocks(monkeypatch, db_session):
    _, headers = await make_actor(monkeypatch, db_session)
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_enabled", False)
    monkeypatch.setattr(s, "rate_limit_user_per_minute", 1)
    assert all(client.get("/api/v1/loan-offers", headers=headers).status_code == 200 for _ in range(4))


async def test_fails_open_when_redis_is_down(monkeypatch, db_session):
    _, headers = await make_actor(monkeypatch, db_session)
    s = get_settings()
    monkeypatch.setattr(s, "redis_url", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(s, "rate_limit_user_per_minute", 1)
    assert all(client.get("/api/v1/loan-offers", headers=headers).status_code == 200 for _ in range(3))
