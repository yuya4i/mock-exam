"""Tests for /api/quiz/regenerate-question session/question validation
(SEC-3 / Red Team P1).

Before the fix, the endpoint would happily spin up an LLM call for
any session_id/question_id pair the caller chose, even when:
  - session_id pointed to a session that doesn't exist; the result was
    silently dropped (persisted=false) but the LLM cycles were spent.
  - question_id pointed to a question that isn't in the (otherwise
    valid) session; same silent no-op outcome.

Both are wasted resource + abuse vectors. Fix: short-circuit with
404 *before* invoking the model.
"""
from __future__ import annotations

import importlib
import json

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
    import app.api.quiz as quiz_mod
    importlib.reload(quiz_mod)
    import app as app_mod
    importlib.reload(app_mod)

    db_mod.init_db()
    return app_mod.app.test_client()


def _seed_session(sid="sess-test-001", question_ids=("Q001", "Q002")):
    from app.database import get_connection
    conn = get_connection()
    try:
        questions = [
            {"id": qid, "question": f"q {qid}", "topic": "t",
             "level": "K2", "options": {}, "answer": "a"}
            for qid in question_ids
        ]
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                question_count, difficulty, levels, questions, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, "test-model", "src", "web", "cat",
             len(questions), "easy", "[]",
             json.dumps(questions, ensure_ascii=False),
             "2024-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _payload(**overrides):
    base = {
        "source": "https://example.com",
        "model": "test-model",
        "level": "K2",
        "difficulty": "easy",
    }
    base.update(overrides)
    return base


def test_regen_with_unknown_session_id_returns_404(client):
    """Caller specified a session_id that no row exists for. Don't
    burn LLM cycles — refuse early with 404."""
    r = client.post(
        "/api/quiz/regenerate-question",
        json=_payload(session_id="sess-does-not-exist", question_id="Q001"),
    )
    assert r.status_code == 404, r.get_json()
    assert "セッション" in (r.get_json() or {}).get("error", ""), r.get_json()


def test_regen_with_unknown_question_id_returns_404(client):
    """Session exists but question_id isn't in it. Same: 404."""
    _seed_session(question_ids=("Q001", "Q002"))
    r = client.post(
        "/api/quiz/regenerate-question",
        json=_payload(session_id="sess-test-001", question_id="Q099"),
    )
    assert r.status_code == 404, r.get_json()
    assert "問題" in (r.get_json() or {}).get("error", ""), r.get_json()


def test_regen_with_only_session_id_returns_400(client):
    """A session_id without a question_id is meaningless for a
    persistence-targeted regen — reject with 400 instead of silently
    treating it as 'not persisted'."""
    _seed_session()
    r = client.post(
        "/api/quiz/regenerate-question",
        json=_payload(session_id="sess-test-001"),
    )
    assert r.status_code == 400, r.get_json()


def test_regen_without_any_session_id_still_allowed(client):
    """The pure 'transient regen' (no persistence) path stays open —
    that's how the FE handles a SyntaxError before a session is saved.
    We only assert this returns NOT 400/404; the LLM may 503 in CI."""
    r = client.post("/api/quiz/regenerate-question", json=_payload())
    assert r.status_code not in (400, 404), r.get_json()
