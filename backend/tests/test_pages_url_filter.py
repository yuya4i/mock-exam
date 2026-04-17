"""Tests that ContentService._build_result drops non-http(s) page URLs
(SEC-12 / FRONTEND-9 / Red Team P1).

The frontend renders pages[].url into <a :href> attributes so any
javascript: / data: / vbscript: / file: scheme arriving from a
malicious scrape target would be one click away from XSS. The
backend now filters at the build-result chokepoint.
"""
from __future__ import annotations

import pytest

from app.services.content_service import CamoufoxPlugin, _is_http_url


@pytest.mark.parametrize("url, expected", [
    ("https://example.com/page", True),
    ("http://example.com/page", True),
    ("HTTPS://EXAMPLE.COM/page", True),
    ("javascript:alert(1)", False),
    ("data:text/html,<script>alert(1)</script>", False),
    ("vbscript:msgbox(1)", False),
    ("file:///etc/passwd", False),
    ("ftp://example.com/x", False),
    ("//example.com/page", False),  # protocol-relative — not safe in href
    ("/relative/path", False),
    ("", False),
    (None, False),
    (12345, False),
    ("   ", False),
])
def test_is_http_url(url, expected):
    assert _is_http_url(url) is expected


def test_build_result_drops_non_http_pages():
    svc = CamoufoxPlugin()
    pages = [
        {"url": "https://example.com/a", "title": "Page A", "depth": 1},
        {"url": "javascript:alert(1)",   "title": "Evil",   "depth": 2},
        {"url": "http://example.com/b",  "title": "Page B", "depth": 1},
        {"url": "data:text/html,x",      "title": "Evil2",  "depth": 2},
    ]
    result = svc._build_result(
        source="https://example.com",
        contents=["body"],
        pages=pages,
        depth=2,
        found_types={"table"},
    )
    safe_urls = [p["url"] for p in result["pages"]]
    assert safe_urls == ["https://example.com/a", "http://example.com/b"]
    assert result["page_count"] == 2


def test_build_result_handles_all_unsafe():
    svc = CamoufoxPlugin()
    pages = [
        {"url": "javascript:alert(1)", "title": "X", "depth": 1},
        {"url": "data:x",              "title": "Y", "depth": 1},
    ]
    result = svc._build_result(
        source="https://example.com",
        contents=["body"],
        pages=pages,
        depth=1,
        found_types={"table"},
    )
    assert result["pages"] == []
    assert result["page_count"] == 0
    # title falls back to source when no safe pages remain
    assert result["title"] == "https://example.com"
