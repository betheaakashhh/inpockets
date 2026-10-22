from types import SimpleNamespace

import pytest

from app.core.client_ip import get_client_ip
from app.core.config import get_settings


def req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(
        client=SimpleNamespace(host=peer) if peer else None,
        headers=headers,
    )


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "trusted_proxy_count", 0)
    monkeypatch.setattr(s, "trusted_proxy_cidrs", None)
    return s


def test_header_ignored_by_default(settings):
    assert get_client_ip(req("10.0.0.5", "1.2.3.4")) == "10.0.0.5"


def test_spoofed_leading_entries_are_ignored_behind_one_proxy(settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    # client forged "9.9.9.9"; the trusted proxy appended the real peer last.
    assert get_client_ip(req("10.0.0.5", "9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_two_trusted_proxies(settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 2)
    assert get_client_ip(req("10.0.0.5", "9.9.9.9, 203.0.113.7, 10.1.1.1")) == "203.0.113.7"


def test_too_few_hops_falls_back_to_peer(settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 2)
    assert get_client_ip(req("10.0.0.5", "203.0.113.7")) == "10.0.0.5"


def test_invalid_header_value_falls_back_to_peer(settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    assert get_client_ip(req("10.0.0.5", "not-an-ip")) == "10.0.0.5"


def test_cidr_restriction(settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    assert get_client_ip(req("10.0.0.5", "203.0.113.7")) == "203.0.113.7"
    # Direct connection from outside the trusted range cannot forge the header.
    assert get_client_ip(req("198.51.100.9", "203.0.113.7")) == "198.51.100.9"


def test_no_peer_and_ipv6(settings, monkeypatch):
    assert get_client_ip(req(None)) is None
    assert get_client_ip(req("2001:db8::1")) == "2001:db8::1"
