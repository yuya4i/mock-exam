"""Tests for documents API DELETE behavior.

Covers BACKEND-1 (Red Team P0): a quiz_session row that references a
document via FK previously caused the document DELETE to fail with
``sqlite3.IntegrityError`` (PRAGMA foreign_keys=ON + no ON DELETE
clause defaults to RESTRICT). The fix detaches the references first
(SET NULL) so historical sessions are preserved while the document
is removed.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Hermetic Flask client backed by a per-test SQLite file."""
    db_path = tmp_path / "test.db"
    history_path = tmp_path / "history.json"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("HISTORY_FILE", str(history_path))

    # Re-import so module-level DB_PATH = resolve_data_path(...) picks up
    # our env override. paths.py is the source of resolution.
    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    import app as app_mod
    importlib.reload(app_mod)

    db_mod.init_db()
    return app_mod.app.test_client()


def _create_document(client, *, content="lorem ipsum doc body"):
    r = client.post(
        "/api/documents",
        json={
            "title": "test doc",
            "url": "https://example.com/test",
            "content": content,
            "source_type": "web",
            "page_count": 1,
            "doc_types": [],
        },
    )
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _insert_session_referencing(doc_id: int, session_id: str = "sess-test-001"):
    """Insert a minimal quiz_session row that references the doc.

    Done via direct SQL because the real /api/quiz/generate flow needs
    Ollama; we only need the FK relationship for this test.
    """
    from app.database import get_connection
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, document_id, model, source_title, source_type,
                category, question_count, difficulty, levels, questions,
                generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, doc_id, "test-model", "test source", "web",
             "test cat", 1, "easy", "[1,2]", "[]",
             "2024-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def test_delete_document_with_no_session_returns_200(client):
    doc_id = _create_document(client)
    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 200


def test_delete_document_preserves_referencing_sessions(client):
    """Regression for BACKEND-1: a session-bound document must still be
    deletable, and the session row must remain (with document_id=NULL)
    so the user's quiz history isn't silently destroyed."""
    doc_id = _create_document(client)
    _insert_session_referencing(doc_id)

    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 200, (
        f"DELETE should not fail with FK error; got {r.status_code} {r.get_json()}"
    )

    from app.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT document_id FROM quiz_sessions WHERE session_id = ?",
            ("sess-test-001",),
        ).fetchone()
        assert row is not None, "session was destroyed (should be preserved)"
        assert row["document_id"] is None, (
            f"session.document_id should be NULL after parent doc delete, "
            f"got {row['document_id']!r}"
        )
    finally:
        conn.close()


def test_delete_nonexistent_document_returns_404(client):
    r = client.delete("/api/documents/99999")
    assert r.status_code == 404
