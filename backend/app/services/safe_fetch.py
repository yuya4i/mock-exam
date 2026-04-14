"""
safe_fetch
==========

Deny-by-default outbound URL fetch policy.

Goals
-----
Given a user-supplied URL, this module decides whether a backend service
may dereference it, and if so, performs the fetch under strict limits.

The default policy is strict because the primary caller (``ContentService``)
takes arbitrary URLs from end users and crawls them; without a guard, the
app would be a trivial SSRF vector to local, cloud-metadata, or LAN
services.

Policy (defaults)
-----------------
* Scheme: only ``https``. ``http`` is rejected.
* Hostname resolution: every A/AAAA record returned by ``getaddrinfo`` must
  be a **public** IP. If any resolved IP is loopback / link-local /
  private / multicast / reserved / unspecified, the URL is rejected —
  this neutralizes the common DNS-based SSRF tricks (e.g. ``localtest.me``).
* Cloud metadata endpoints (``169.254.169.254``, ``100.100.100.200``,
  ``fd00:ec2::254``) are rejected **unconditionally**, even when the
  private-network override is on.
* Redirects are followed manually, at most ``MAX_REDIRECTS`` (3 by
  default) deep; every hop is re-validated.
* Response body is streamed and truncated at ``MAX_FETCH_BYTES`` (10 MiB
  by default); the returned ``requests.Response`` has ``.content``
  materialized to the truncated bytes.
* Connect/read timeout is ``(5s, 30s)`` unless overridden.

Opt-in overrides (environment variables)
----------------------------------------
* ``ALLOW_HTTP=1`` — also allow the ``http`` scheme.
* ``ALLOW_PRIVATE_NETWORKS=1`` — also allow loopback / link-local /
  private / reserved targets (metadata IPs remain denied).
* ``MAX_FETCH_BYTES=<int>`` — override the body size cap.
* ``MAX_REDIRECTS=<int>`` — override the redirect cap (``0`` disables).

Residual risk — DNS rebinding
-----------------------------
``check_url`` resolves the hostname once and validates each returned IP.
A TOCTOU race is possible between resolution and socket connect because
``requests`` re-resolves the hostname when opening the TCP connection.
Mitigation at this level is best-effort; for high-value deployments,
confine the backend to a network namespace without a route to RFC1918.
This is documented in ``SECURITY.md``.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Tunables & policy
# --------------------------------------------------------------------------
DEFAULT_MAX_FETCH_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = (5, 30)  # (connect, read)
DEFAULT_CHUNK_SIZE = 64 * 1024

# Cloud metadata endpoints. These are rejected even when the private-network
# override is enabled — operators almost never actually want the app to call
# them, and giving it the ability to is a well-known credential-theft path.
METADATA_HOSTS_V4 = frozenset({
    "169.254.169.254",  # AWS, GCP, Azure, OpenStack
    "100.100.100.200",  # Alibaba Cloud
})
METADATA_HOSTS_V6 = frozenset({
    "fd00:ec2::254",    # AWS IMDSv2 via IPv6
})


class UnsafeURLError(ValueError):
    """Raised when a URL is rejected by the policy."""


class ResponseTooLargeError(IOError):
    """Raised when the response body would exceed the configured size cap."""


def _env_flag(name: str) -> bool:
    raw = os.getenv(name, "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, *, min_val: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} is not an int; using default {default}")
        return default
    return max(value, min_val)


@dataclass(frozen=True)
class FetchPolicy:
    """Immutable snapshot of the active policy.

    Defaults read the env at construction time. Callers that need a
    different policy (e.g. to test with the overrides) should construct
    ``FetchPolicy(allow_http=True, ...)`` explicitly.
    """

    allow_http: bool = field(
        default_factory=lambda: _env_flag("ALLOW_HTTP"),
    )
    allow_private_networks: bool = field(
        default_factory=lambda: _env_flag("ALLOW_PRIVATE_NETWORKS"),
    )
    max_bytes: int = field(
        default_factory=lambda: _env_int(
            "MAX_FETCH_BYTES", DEFAULT_MAX_FETCH_BYTES, min_val=1024,
        ),
    )
    max_redirects: int = field(
        default_factory=lambda: _env_int(
            "MAX_REDIRECTS", DEFAULT_MAX_REDIRECTS, min_val=0,
        ),
    )

    @property
    def allowed_schemes(self) -> frozenset[str]:
        return frozenset({"https", "http"}) if self.allow_http else frozenset({"https"})


# --------------------------------------------------------------------------
# IP classification
# --------------------------------------------------------------------------
def _as_ip_or_none(text: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return None


def _is_metadata_ip(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv4Address):
        return str(ip) in METADATA_HOSTS_V4
    if isinstance(ip, ipaddress.IPv6Address):
        if str(ip) in METADATA_HOSTS_V6:
            return True
        if ip.ipv4_mapped is not None:
            return _is_metadata_ip(ip.ipv4_mapped)
    return False


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    """Return True iff the IP is a routable public address suitable for
    outbound fetches. Metadata IPs are NEVER considered public even though
    ipaddress considers link-local IPv4 as just "link-local"."""
    if _is_metadata_ip(ip):
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_public_ip(ip.ipv4_mapped)
    if ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    if ip.is_private or ip.is_reserved or ip.is_unspecified:
        return False
    return True


def _resolve_all_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    """Resolve ``hostname`` to every A/AAAA record. May raise ``socket.gaierror``."""
    out: list[ipaddress._BaseAddress] = []
    for family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(
        hostname, None, type=socket.SOCK_STREAM,
    ):
        if family == socket.AF_INET:
            out.append(ipaddress.IPv4Address(sockaddr[0]))
        elif family == socket.AF_INET6:
            # strip IPv6 zone-id ("fe80::1%eth0")
            addr = sockaddr[0].split("%", 1)[0]
            out.append(ipaddress.IPv6Address(addr))
    return out


# --------------------------------------------------------------------------
# URL validation
# --------------------------------------------------------------------------
def check_url(url: str, policy: Optional[FetchPolicy] = None) -> None:
    """Validate ``url`` against the SSRF policy.

    Raises ``UnsafeURLError`` with a message safe to surface to the client
    when validation fails. Returns ``None`` on success.
    """
    policy = policy or FetchPolicy()

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise UnsafeURLError(f"無効なURL形式です: {e}") from e

    scheme = (parsed.scheme or "").lower()
    if scheme not in policy.allowed_schemes:
        allowed_list = ", ".join(sorted(policy.allowed_schemes))
        raise UnsafeURLError(
            f"スキーム '{scheme or '(なし)'}' は許可されていません。許可: {allowed_list}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URLにホスト名が含まれていません。")

    # IP-literal URLs skip DNS resolution.
    literal_ip = _as_ip_or_none(hostname)
    if literal_ip is not None:
        if _is_metadata_ip(literal_ip):
            raise UnsafeURLError(
                f"クラウドメタデータエンドポイントへのアクセスは拒否されました: {hostname}"
            )
        if not _is_public_ip(literal_ip) and not policy.allow_private_networks:
            raise UnsafeURLError(
                f"プライベート/ループバック/リンクローカル宛のアクセスは拒否されました: {hostname}"
            )
        return

    try:
        resolved = _resolve_all_ips(hostname)
    except socket.gaierror as e:
        raise UnsafeURLError(f"ホスト名を解決できませんでした: {hostname} ({e})") from e

    if not resolved:
        raise UnsafeURLError(f"ホスト名を解決できませんでした: {hostname}")

    # EVERY resolved IP must pass. This stops DNS-based tricks where a
    # hostname resolves to both a public IP (for the validator) and a
    # private IP (for the attacker).
    for ip in resolved:
        if _is_metadata_ip(ip):
            raise UnsafeURLError(
                f"クラウドメタデータエンドポイントへのアクセスは拒否されました: {hostname} -> {ip}"
            )
        if not _is_public_ip(ip) and not policy.allow_private_networks:
            raise UnsafeURLError(
                f"プライベート/ループバック/リンクローカル宛のアクセスは拒否されました: {hostname} -> {ip}"
            )


def is_url_allowed(url: str, policy: Optional[FetchPolicy] = None) -> bool:
    """Boolean form of :func:`check_url`. Does not raise."""
    try:
        check_url(url, policy)
        return True
    except UnsafeURLError:
        return False


# --------------------------------------------------------------------------
# Actual fetch
# --------------------------------------------------------------------------
def safe_get(
    url: str,
    *,
    policy: Optional[FetchPolicy] = None,
    timeout=DEFAULT_TIMEOUT,
    headers: Optional[dict] = None,
    session: Optional[requests.Session] = None,
) -> requests.Response:
    """``requests.get`` with the SSRF policy applied at every hop.

    The returned Response has ``.content`` fully materialized (truncated to
    ``policy.max_bytes``). Callers should NOT call ``iter_content`` / read
    ``raw`` on it.

    Raises:
        UnsafeURLError: if the initial URL or any redirect target fails the
            policy, or if the redirect cap is exceeded.
        ResponseTooLargeError: if the response body exceeds
            ``policy.max_bytes``.
        requests.RequestException: for transport-level failures.
    """
    policy = policy or FetchPolicy()
    s = session or requests

    current_url = url
    # One extra iteration on top of max_redirects so the original request
    # itself is a "hop" — matches how requests normally counts.
    for hop in range(policy.max_redirects + 1):
        check_url(current_url, policy)

        resp = s.get(
            current_url,
            allow_redirects=False,
            stream=True,
            timeout=timeout,
            headers=headers,
        )

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise UnsafeURLError("リダイレクトに Location ヘッダがありません。")
            if hop >= policy.max_redirects:
                raise UnsafeURLError(
                    f"リダイレクト回数が上限 ({policy.max_redirects}) を超えました。"
                )
            current_url = urljoin(current_url, location)
            continue

        # Non-redirect: stream the body and enforce the byte cap.
        try:
            body = bytearray()
            for chunk in resp.iter_content(chunk_size=DEFAULT_CHUNK_SIZE):
                if not chunk:
                    continue
                if len(body) + len(chunk) > policy.max_bytes:
                    # Still fill up to the cap so callers get a predictable
                    # partial body if they choose to tolerate the error.
                    remaining = policy.max_bytes - len(body)
                    if remaining > 0:
                        body.extend(chunk[:remaining])
                    raise ResponseTooLargeError(
                        f"レスポンス本文が上限 {policy.max_bytes} バイトを超えました。"
                    )
                body.extend(chunk)
            resp._content = bytes(body)  # type: ignore[attr-defined]
        finally:
            resp.close()
        return resp

    # Unreachable: the loop either returns or raises on redirect overflow.
    raise UnsafeURLError("内部エラー: リダイレクト処理が完了しませんでした。")
