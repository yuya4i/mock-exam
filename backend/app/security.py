"""
Lightweight opt-in API authentication.

When ``API_TOKEN`` is set in the environment, every request to a path
starting with ``/api/`` must carry ``Authorization: Bearer <token>``.
When ``API_TOKEN`` is unset (or empty), the API remains open — this
preserves the zero-friction local development experience while letting
operators turn on a token with one env var.

The middleware also emits a one-shot startup warning when the backend is
configured to accept connections from non-loopback addresses without a
token, because that combination is the highest-impact footgun.

Design notes
------------
* ``hmac.compare_digest`` is used so the comparison is constant-time and
  does not leak token length or prefix through timing.
* ``OPTIONS`` preflight requests are always allowed; browsers send them
  without an Authorization header, and the flask-cors layer already
  controls origin acceptance.
* The middleware hard-codes a small allowlist of paths that must stay
  reachable even with a token configured — currently ``/api/health``,
  so monitoring probes can detect a misconfigured token without
  credentials. This is an operator convenience, not a security
  weakening (the endpoint returns no privileged data).
"""
from __future__ import annotations

import hmac
import logging
import os

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

# Endpoints that remain reachable without a token even when API_TOKEN
# is configured. Keep this list small and review each addition.
_AUTH_EXEMPT_PATHS = frozenset({
    "/api/health",
})

# P1-G removed the ``?api_token=`` query-parameter carve-out for
# /api/content/scrape-stream because the frontend now consumes that SSE
# stream via ``fetch`` instead of ``EventSource``. ``fetch`` honors the
# Authorization header, so no in-URL secret is ever required. Tokens in
# URLs leak through access logs, browser histories, and Referer headers
# — this is a real reduction in attack surface.


def _get_expected_token() -> str:
    """Return the configured API token stripped of whitespace, or ''."""
    raw = os.getenv("API_TOKEN", "")
    return raw.strip() if isinstance(raw, str) else ""


def _extract_bearer_token(header_value: str | None) -> str | None:
    """Return the bearer token from ``header_value`` or ``None``."""
    if not header_value:
        return None
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0].lower(), parts[1].strip()
    if scheme != "bearer" or not token:
        return None
    return token


def _require_token():
    """Flask ``before_request`` hook enforcing the API_TOKEN contract.

    Returns ``None`` to continue, or a (json, status) tuple to short-circuit.
    """
    # Non-API paths (static, unknown) are left alone.
    if not request.path.startswith("/api/"):
        return None

    # CORS preflight: always allow; flask-cors handles origin acceptance.
    if request.method == "OPTIONS":
        return None

    expected = _get_expected_token()
    if not expected:
        # Token not configured → auth disabled. This is the local-dev default.
        return None

    if request.path in _AUTH_EXEMPT_PATHS:
        return None

    provided = _extract_bearer_token(request.headers.get("Authorization"))
    if provided is None:
        return jsonify({"error": "認証が必要です。"}), 401

    if not hmac.compare_digest(provided, expected):
        return jsonify({"error": "認証に失敗しました。"}), 401

    return None


def register_auth(app: Flask) -> None:
    """Wire the auth middleware into the Flask app."""
    app.before_request(_require_token)


def warn_if_insecurely_exposed() -> None:
    """Emit a visible warning when API_TOKEN is unset AND the backend is
    configured to accept non-loopback connections.

    Uses the ``FLASK_RUN_HOST`` (Flask CLI) and a handful of common
    deployment env vars as a heuristic. False positives are intentional —
    it is better to nag once than to silently ship a wide-open API.
    """
    if _get_expected_token():
        return  # token configured: no warning needed

    # Order: explicit BIND_HOST first, then FLASK_RUN_HOST, then the
    # widespread habit of binding 0.0.0.0 inside containers.
    candidates = (
        os.getenv("BIND_HOST"),
        os.getenv("FLASK_RUN_HOST"),
        os.getenv("HOST"),
    )
    bind_host = next((c for c in candidates if c), None)

    # Inside Docker we always bind 0.0.0.0 by CMD (see Dockerfile); treat
    # "inside a container" as the default non-loopback case.
    inside_container = os.path.exists("/.dockerenv") or os.getenv("container") is not None

    non_loopback = False
    if bind_host is not None:
        non_loopback = bind_host not in ("127.0.0.1", "localhost", "::1")
    elif inside_container:
        non_loopback = True

    if non_loopback:
        logger.warning(
            "API_TOKEN が未設定のままネットワーク公開されています。"
            " ローカル開発以外では `API_TOKEN` を設定してください (SECURITY.md 参照)。"
        )
