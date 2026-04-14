"""
Tests for the opt-in API_TOKEN middleware (see backend/app/security.py).

Uses the live Flask app via test client. The conftest.py bootstrap
wipes API_TOKEN so each test sets it explicitly via monkeypatch.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def make_client(monkeypatch):
    """Reload app so security.register_auth() picks up the current env."""
    def _factory(api_token: str | None = None):
        if api_token is None:
            monkeypatch.delenv("API_TOKEN", raising=False)
        else:
            monkeypatch.setenv("API_TOKEN", api_token)
        import app as app_module
        importlib.reload(app_module)
        return app_module.app.test_client()
    return _factory


def test_no_token_configured_allows_everything(make_client):
    client = make_client(api_token=None)
    r = client.get("/api/health")
    assert r.status_code == 200


def test_token_configured_without_header_401(make_client):
    client = make_client(api_token="s3cret")
    r = client.get("/api/models")
    assert r.status_code == 401


def test_token_configured_wrong_header_401(make_client):
    client = make_client(api_token="s3cret")
    r = client.get("/api/models", headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401


def test_token_configured_correct_header_passes(make_client):
    client = make_client(api_token="s3cret")
    r = client.get("/api/models", headers={"Authorization": "Bearer s3cret"})
    # Upstream may return 503 (Ollama absent in tests) but NOT 401.
    assert r.status_code != 401


def test_health_is_always_exempt(make_client):
    client = make_client(api_token="s3cret")
    r = client.get("/api/health")
    assert r.status_code == 200


def test_options_preflight_is_exempt(make_client):
    client = make_client(api_token="s3cret")
    r = client.open(
        "/api/models",
        method="OPTIONS",
        headers={"Origin": "http://localhost:1234",
                 "Access-Control-Request-Method": "GET"},
    )
    # CORS preflight should not 401. It may 200 or 204 depending on flask-cors.
    assert r.status_code != 401


def test_non_api_path_is_exempt(make_client):
    client = make_client(api_token="s3cret")
    # A nonexistent non-API path. Expect 404, not 401 — middleware should
    # not gate non-/api/ paths.
    r = client.get("/not-api")
    assert r.status_code != 401


def test_query_param_token_is_no_longer_accepted_anywhere(make_client):
    """P1-G removed the ?api_token= carve-out for SSE endpoints. The
    frontend now uses fetch+stream and sends the Authorization header
    just like every other request, so no path should accept the token
    via query string anymore."""
    client = make_client(api_token="s3cret")
    # Was accepted pre-P1-G:
    r = client.get(
        "/api/content/scrape-stream"
        "?source=https://example.com&depth=1&api_token=s3cret",
    )
    assert r.status_code == 401
    # And still rejected on non-SSE endpoints (regression check):
    r = client.get("/api/models?api_token=s3cret")
    assert r.status_code == 401


def test_scrape_stream_accepts_authorization_header(make_client):
    """The SSE endpoint must accept the same Bearer header as other
    endpoints (this is what the new fetch-based frontend sends)."""
    client = make_client(api_token="s3cret")
    r = client.get(
        "/api/content/scrape-stream?source=https://example.com&depth=1",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code != 401


def test_constant_time_compare_accepts_matching_token(make_client):
    # Sanity: identical-length mismatched tokens still 401 (not a bug
    # where matched length short-circuits).
    client = make_client(api_token="abcdefgh")
    r = client.get("/api/models", headers={"Authorization": "Bearer abcdefg_"})
    assert r.status_code == 401
    r = client.get("/api/models", headers={"Authorization": "Bearer abcdefgh"})
    assert r.status_code != 401
