"""Client IP resolution that cannot be spoofed through X-Forwarded-For.

By default the header is ignored. Behind a load balancer, configure
TRUSTED_PROXY_COUNT (and optionally TRUSTED_PROXY_CIDRS) so only addresses
appended by proxies we operate are believed.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from app.core.config import Settings, get_settings


def _valid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _peer_is_trusted(peer: str | None, cidrs: str | None) -> bool:
    if not cidrs:
        return True
    if peer is None:
        return False
    try:
        address = ipaddress.ip_address(peer)
        return any(
            address in ipaddress.ip_network(c.strip(), strict=False)
            for c in cidrs.split(",")
            if c.strip()
        )
    except ValueError:
        return False


def get_client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """Return a valid IP string (safe for an INET column) or None."""
    s = settings or get_settings()
    peer = _valid(request.client.host if request.client else None)

    if s.trusted_proxy_count > 0 and _peer_is_trusted(peer, s.trusted_proxy_cidrs):
        header = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in header.split(",") if h.strip()]
        if len(hops) >= s.trusted_proxy_count:
            candidate = _valid(hops[-s.trusted_proxy_count])
            if candidate is not None:
                return candidate
    return peer
