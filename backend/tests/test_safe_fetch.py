"""
SSRF policy unit tests (see backend/app/services/safe_fetch.py).

Covers:
    - scheme allowlist (default: https only)
    - cloud-metadata denylist (always denied, even under the
      ALLOW_PRIVATE_NETWORKS override)
    - IP classification (loopback / link-local / RFC1918 / multicast /
      reserved / unspecified / public)
    - ALLOW_HTTP / ALLOW_PRIVATE_NETWORKS env overrides
    - DNS rebinding: hostname resolves to a mix of public and private IPs,
      or to a private IP, or to a metadata IP
    - gaierror surfaces as UnsafeURLError

No network IO is performed. ``socket.getaddrinfo`` is monkeypatched.
"""
from __future__ import annotations

import socket
from unittest import mock

import pytest

from app.services.safe_fetch import FetchPolicy, UnsafeURLError, check_url


# ------------------------------------------------------------------
# Default policy (strict)
# ------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "gopher://example.com/",
    ],
)
def test_default_policy_rejects_non_https_schemes(url):
    with pytest.raises(UnsafeURLError, match="スキーム"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/",       # AWS/GCP/Azure v4
        "https://100.100.100.200/",       # Alibaba
        "https://[fd00:ec2::254]/",       # AWS IPv6 IMDSv2
    ],
)
def test_metadata_ips_always_denied(url):
    with pytest.raises(UnsafeURLError, match="メタデータ"):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",        # loopback v4
        "https://[::1]/",            # loopback v6
        "https://10.0.0.1/",         # RFC1918
        "https://172.16.0.1/",       # RFC1918
        "https://192.168.1.1/",      # RFC1918
        "https://169.254.1.1/",      # link-local v4 (non-metadata)
        "https://[fe80::1]/",        # link-local v6
        "https://0.0.0.0/",          # unspecified
    ],
)
def test_default_policy_rejects_private_ips(url):
    with pytest.raises(UnsafeURLError, match="プライベート"):
        check_url(url)


@pytest.mark.parametrize("url", ["https://8.8.8.8/", "https://1.1.1.1/"])
def test_default_policy_allows_public_ips(url):
    check_url(url)  # no raise


@pytest.mark.parametrize("url", ["https:///", ""])
def test_malformed_urls(url):
    with pytest.raises(UnsafeURLError):
        check_url(url)


# ------------------------------------------------------------------
# ALLOW_HTTP
# ------------------------------------------------------------------
def test_allow_http_allows_plain_http_to_public_ips():
    p = FetchPolicy(allow_http=True, allow_private_networks=False,
                    max_bytes=1024, max_redirects=3)
    check_url("http://8.8.8.8/", p)


def test_allow_http_still_rejects_private():
    p = FetchPolicy(allow_http=True, allow_private_networks=False,
                    max_bytes=1024, max_redirects=3)
    with pytest.raises(UnsafeURLError):
        check_url("http://127.0.0.1/", p)


def test_allow_http_still_rejects_metadata():
    p = FetchPolicy(allow_http=True, allow_private_networks=False,
                    max_bytes=1024, max_redirects=3)
    with pytest.raises(UnsafeURLError, match="メタデータ"):
        check_url("http://169.254.169.254/", p)


# ------------------------------------------------------------------
# ALLOW_PRIVATE_NETWORKS
# ------------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://127.0.0.1/", "https://10.0.0.1/"])
def test_allow_private_allows_loopback_and_rfc1918(url):
    p = FetchPolicy(allow_http=False, allow_private_networks=True,
                    max_bytes=1024, max_redirects=3)
    check_url(url, p)


@pytest.mark.parametrize(
    "url", ["https://169.254.169.254/", "https://[fd00:ec2::254]/"],
)
def test_allow_private_still_rejects_metadata(url):
    p = FetchPolicy(allow_http=False, allow_private_networks=True,
                    max_bytes=1024, max_redirects=3)
    with pytest.raises(UnsafeURLError, match="メタデータ"):
        check_url(url, p)


# ------------------------------------------------------------------
# DNS-level attacks
# ------------------------------------------------------------------
def _fake_gai(addrs):
    """Build a getaddrinfo replacement that returns the given (ip, port)
    tuples as AF_INET / AF_INET6 entries based on IP version."""
    import ipaddress as _ip

    def _gai(host, *a, **k):
        out = []
        for ip, port in addrs:
            parsed = _ip.ip_address(ip)
            fam = socket.AF_INET if parsed.version == 4 else socket.AF_INET6
            out.append((fam, 0, 0, "", (ip, port)))
        return out
    return _gai


def test_dns_returning_mixed_public_and_private_is_rejected():
    fake = _fake_gai([("8.8.8.8", 0), ("127.0.0.1", 0)])
    with mock.patch("socket.getaddrinfo", fake):
        with pytest.raises(UnsafeURLError, match="プライベート"):
            check_url("https://evil.example.com/")


def test_dns_returning_all_public_is_allowed():
    fake = _fake_gai([("8.8.8.8", 0)])
    with mock.patch("socket.getaddrinfo", fake):
        check_url("https://example.com/")


def test_dns_pointing_to_loopback_is_rejected():
    fake = _fake_gai([("127.0.0.1", 0)])
    with mock.patch("socket.getaddrinfo", fake):
        with pytest.raises(UnsafeURLError, match="プライベート"):
            check_url("https://localtest.me/")


def test_dns_pointing_to_metadata_is_rejected():
    fake = _fake_gai([("169.254.169.254", 0)])
    with mock.patch("socket.getaddrinfo", fake):
        with pytest.raises(UnsafeURLError, match="メタデータ"):
            check_url("https://metadata.example.com/")


def test_dns_resolution_failure_surfaces_as_unsafe_url_error():
    def _boom(*a, **k):
        raise socket.gaierror("Name or service not known")

    with mock.patch("socket.getaddrinfo", _boom):
        with pytest.raises(UnsafeURLError, match="ホスト名を解決"):
            check_url("https://does-not-exist.example/")
