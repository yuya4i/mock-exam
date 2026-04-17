"""Tests for SEC-8 (HEAD method auth) + SEC-9 (NAT64 prefix bypass).

SEC-9: an IPv6 address in the well-known NAT64 prefix
``64:ff9b::/96`` (RFC 6052) embeds an IPv4 in the low 32 bits.
``ipaddress.IPv6Address.ipv4_mapped`` only handles ``::ffff:0:0/96``,
so a URL like ``http://[64:ff9b::ac10:1]/`` (which translates to
172.16.0.1) used to slip past the IPv4 private check.

SEC-8: HEAD requests must NOT bypass the API_TOKEN middleware.
Flask routes that allow GET also auto-handle HEAD; without an
explicit check, HEAD could be a covert exfil channel.
"""
from __future__ import annotations

import importlib

import pytest

from app.services.safe_fetch import FetchPolicy, is_url_allowed


@pytest.mark.parametrize("url", [
    "http://[64:ff9b::ac10:1]/",      # 172.16.0.1 (private)
    "http://[64:ff9b::a00:1]/",       # 10.0.0.1 (private)
    "http://[64:ff9b::7f00:1]/",      # 127.0.0.1 (loopback)
    "http://[64:ff9b::a9fe:a9fe]/",   # 169.254.169.254 (metadata!)
])
def test_nat64_embedded_private_ipv4_is_blocked(url):
    policy = FetchPolicy(allow_http=True)
    assert is_url_allowed(url, policy) is False


def test_nat64_embedded_public_ipv4_is_allowed():
    """1.1.1.1 via NAT64 should still pass (we only block based on the
    embedded IPv4's class, not the prefix itself)."""
    # 1.1.1.1 = 0x01010101
    url = "http://[64:ff9b::101:101]/"
    policy = FetchPolicy(allow_http=True)
    assert is_url_allowed(url, policy) is True


@pytest.fixture
def auth_client(monkeypatch):
    """Reload app with an API_TOKEN configured."""
    monkeypatch.setenv("API_TOKEN", "topsecret")
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


def test_head_request_without_token_is_401(auth_client):
    """SEC-8: HEAD must be auth'd same as GET. Flask auto-routes HEAD
    onto any GET handler so it's part of the API surface."""
    r = auth_client.head("/api/models")
    assert r.status_code == 401


def test_head_request_with_token_passes(auth_client):
    r = auth_client.head(
        "/api/models", headers={"Authorization": "Bearer topsecret"},
    )
    # Upstream may 503 (no Ollama in CI) but never 401.
    assert r.status_code != 401


def test_head_health_remains_exempt(auth_client):
    """Health endpoint stays open for monitoring probes."""
    r = auth_client.head("/api/health")
    assert r.status_code != 401
