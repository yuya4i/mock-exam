"""Tests for BACKEND-12 + BACKEND-13.

- BACKEND-12: AnswersRequest answers dict has a max_length cap so a
  malicious POST can't allocate ~unlimited memory in Pydantic's
  validation pass.
- BACKEND-13: score_correct / score_total in the request are ignored
  on save; the route recomputes them from the persisted questions[]
  so an attacker can't inflate analytics.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "h.json"))
    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    # Reload results so the SEC-7 per-session rate-limit dict starts
    # empty (otherwise sequential tests on the same session hit 429).
    import app.api.results as results_mod
    importlib.reload(results_mod)
    import app as app_mod
    importlib.reload(app_mod)
    db_mod.init_db()
    return app_mod.app.test_client()


def _seed_session(sid="sess-score-001"):
    questions = [
        {"id": "Q001", "question": "q1", "topic": "t", "level": "K2",
         "choices": {"a": "x", "b": "y"}, "answer": "a"},
        {"id": "Q002", "question": "q2", "topic": "t", "level": "K2",
         "choices": {"a": "x", "b": "y"}, "answer": "b"},
        {"id": "Q003", "question": "q3", "topic": "t", "level": "K2",
         "choices": {"a": "x", "b": "y"}, "answer": "a"},
    ]
    from app.database import get_connection
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                question_count, difficulty, levels, questions, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, "m", "src", "web", "cat", 3, "easy", "[]",
             json.dumps(questions, ensure_ascii=False),
             "2024-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    return questions


def _read_score(sid):
    from app.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT score_correct, score_total FROM quiz_sessions WHERE session_id = ?",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    return (row["score_correct"], row["score_total"]) if row else None


def test_score_is_recomputed_server_side_ignoring_client(client):
    """BACKEND-13: the client claims a perfect score; the server
    recomputes from the actual answers vs the persisted answer keys."""
    _seed_session()
    r = client.post("/api/results/sess-score-001/answers", json={
        "answers": {"Q001": "a", "Q002": "a", "Q003": "a"},  # 2/3 right
        "score_correct": 999,    # client lies
        "score_total": 999,      # client lies
    })
    assert r.status_code == 200, r.get_json()
    payload = r.get_json()
    assert payload["score_correct"] == 2
    assert payload["score_total"] == 3
    assert _read_score("sess-score-001") == (2, 3)


def test_score_zero_when_all_wrong(client):
    _seed_session()
    r = client.post("/api/results/sess-score-001/answers", json={
        "answers": {"Q001": "b", "Q002": "a", "Q003": "b"},
        "score_correct": 999, "score_total": 999,
    })
    assert r.status_code == 200
    assert _read_score("sess-score-001") == (0, 3)


def test_partial_answers_score_total_is_answered_not_session_total(client):
    """Regression for the analytics-tab "unnatural number" bug.

    User answered only 2 of the 3 seeded questions. score_total must
    reflect "how many you actually attempted" (= 2), not "questions in
    the session" (= 3). Otherwise the displayed accuracy looks like
    "66% of the session" when it's really "100% of attempted".
    The session's total question count is preserved on
    quiz_sessions.question_count (separate column)."""
    _seed_session()
    r = client.post("/api/results/sess-score-001/answers", json={
        "answers": {"Q001": "a", "Q002": "b"},  # only 2 answered, both correct
    })
    assert r.status_code == 200, r.get_json()
    payload = r.get_json()
    assert payload["score_total"] == 2, payload    # answered count
    assert payload["score_correct"] == 2, payload  # both correct
    assert _read_score("sess-score-001") == (2, 2)


def test_blank_answer_strings_not_counted(client):
    """Empty-string entries in the answers dict should not be treated
    as attempts (FE may include "" for not-yet-clicked options under
    some race conditions)."""
    _seed_session()
    r = client.post("/api/results/sess-score-001/answers", json={
        "answers": {"Q001": "a", "Q002": "", "Q003": "   "},
    })
    assert r.status_code == 200, r.get_json()
    assert _read_score("sess-score-001") == (1, 1)


def test_answers_dict_too_large_400(client):
    """BACKEND-12: 1000+ entries is rejected at validation."""
    huge = {f"Q{i:04d}": "a" for i in range(1500)}
    r = client.post("/api/results/sess-score-001/answers", json={"answers": huge})
    assert r.status_code == 400


def test_answer_value_too_long_400(client):
    r = client.post("/api/results/sess-score-001/answers", json={
        "answers": {"Q001": "a" * 100},
    })
    assert r.status_code == 400
