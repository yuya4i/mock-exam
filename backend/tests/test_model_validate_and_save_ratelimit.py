"""Tests for SEC-6 (model name charset) and SEC-7 (per-session
rate limit on answers POST).
"""
from __future__ import annotations

import importlib
import json
import time

import pytest

from app.api._schemas import is_valid_model_name


@pytest.mark.parametrize("name, ok", [
    ("llama3:8b", True),
    ("qwen2.5:7b-instruct", True),
    ("gpt-oss:20b", True),
    ("nomic-embed-text:v1.5", True),
    ("registry/model:tag", True),
    ("a" * 128, True),
    ("a" * 129, False),
    ("", False),
    ("model with space", False),
    ("model;rm -rf /", False),
    ("model$(echo bad)", False),
    ("\u65e5\u672c\u8a9e", False),
    (None, False),
])
def test_is_valid_model_name(name, ok):
    assert is_valid_model_name(name) is ok


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "h.json"))
    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    # Reload results too because the rate-limit dict is module-state
    import app.api.results as results_mod
    importlib.reload(results_mod)
    import app as app_mod
    importlib.reload(app_mod)
    db_mod.init_db()
    return app_mod.app.test_client()


def _seed_session(sid="sess-rate-001"):
    questions = [
        {"id": f"Q{i+1:03d}", "question": f"q{i}", "topic": "t",
         "level": "K2", "choices": {"a": "x"}, "answer": "a"}
        for i in range(3)
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


def test_quiz_generate_with_bad_model_name_400(client):
    r = client.post("/api/quiz/generate", json={
        "source": "https://example.com",
        "model": "bad model;rm -rf /",
        "count": 1,
    })
    assert r.status_code == 400


def test_regen_with_bad_model_name_400(client):
    r = client.post("/api/quiz/regenerate-question", json={
        "source": "https://example.com",
        "model": "bad model",
    })
    assert r.status_code == 400


def test_save_answers_rate_limit_returns_429(client):
    """Two saves under 200ms apart on the same session: second is
    rate-limited."""
    _seed_session()
    r1 = client.post("/api/results/sess-rate-001/answers", json={
        "answers": {"Q001": "a"},
    })
    assert r1.status_code == 200, r1.get_json()
    # Immediately retry
    r2 = client.post("/api/results/sess-rate-001/answers", json={
        "answers": {"Q001": "a"},
    })
    assert r2.status_code == 429, r2.get_json()


def test_save_answers_after_interval_passes(client):
    _seed_session()
    r1 = client.post("/api/results/sess-rate-001/answers", json={
        "answers": {"Q001": "a"},
    })
    assert r1.status_code == 200
    time.sleep(0.25)  # > _SAVE_MIN_INTERVAL_SEC
    r2 = client.post("/api/results/sess-rate-001/answers", json={
        "answers": {"Q001": "a"},
    })
    assert r2.status_code == 200, r2.get_json()


def test_save_answers_different_sessions_independent(client):
    _seed_session("sess-rate-001")
    _seed_session("sess-rate-002")
    r1 = client.post("/api/results/sess-rate-001/answers", json={
        "answers": {"Q001": "a"},
    })
    r2 = client.post("/api/results/sess-rate-002/answers", json={
        "answers": {"Q001": "a"},
    })
    assert r1.status_code == 200
    assert r2.status_code == 200, r2.get_json()
