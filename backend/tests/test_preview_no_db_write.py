"""Tests for the read-only nature of /api/content/preview (BACKEND-3).

The preview endpoint used to call ContentService.fetch() which always
calls _save_to_db() — so a curious user typing a URL into the preview
field would silently persist that document to the production DB.

After the fix, preview() takes a persist=False path through fetch()
and the documents table stays empty until the user explicitly hits
the generate (= scrape-stream) flow which is the real "save" verb.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "history.json"))

    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    # content service is module-level singleton; reload to pick up env
    import app.services.content_service as cs_mod
    importlib.reload(cs_mod)
    import app.api.content as content_api_mod
    importlib.reload(content_api_mod)
    import app as app_mod
    importlib.reload(app_mod)

    db_mod.init_db()
    return app_mod.app.test_client()


def _doc_count():
    from app.database import get_connection
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    finally:
        conn.close()


def test_preview_with_text_input_does_not_persist(client):
    """Plain-text preview must not insert a documents row."""
    assert _doc_count() == 0, "test DB should start empty"

    payload = {
        "source": "Lorem ipsum dolor sit amet, this is a preview-only string.",
        "depth": 1,
        "doc_types": [],
    }
    r = client.post("/api/content/preview", json=payload)
    assert r.status_code == 200, r.get_json()

    assert _doc_count() == 0, (
        "BACKEND-3: /api/content/preview must not persist to documents table"
    )


def test_fetch_with_text_input_does_persist(client):
    """Sanity check: the explicit /api/content/fetch path still saves
    (otherwise the generate flow would lose its document_id)."""
    assert _doc_count() == 0
    payload = {
        "source": "Lorem ipsum dolor sit amet, persisted via fetch endpoint.",
        "depth": 1,
        "doc_types": [],
    }
    r = client.post("/api/content/fetch", json=payload)
    assert r.status_code == 200, r.get_json()
    assert _doc_count() == 1, "fetch should persist (regression check)"
