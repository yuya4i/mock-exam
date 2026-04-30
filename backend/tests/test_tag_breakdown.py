"""Tests for the tag-based analytics endpoint /api/results/tags/breakdown
and the underlying _normalize_tags helper.
"""
from __future__ import annotations

import importlib
import json

import pytest

from app.services.quiz_service import _normalize_tags, MAX_TAGS_PER_QUESTION


# --------------------------------------------------------------------------
# _normalize_tags unit tests
# --------------------------------------------------------------------------
def test_normalize_tags_handles_non_list():
    assert _normalize_tags(None) == []
    assert _normalize_tags("a,b,c") == []
    assert _normalize_tags({"a": 1}) == []


def test_normalize_tags_lowercases_and_trims():
    assert _normalize_tags(["TCP/IP", "  HTTP  "]) == ["tcp/ip", "http"]


def test_normalize_tags_collapses_whitespace():
    assert _normalize_tags(["3 way   handshake"]) == ["3 way handshake"]


def test_normalize_tags_dedupes_after_normalize():
    out = _normalize_tags(["TCP", "tcp", "TCP "])
    assert out == ["tcp"]


def test_normalize_tags_drops_too_short_and_too_long():
    out = _normalize_tags([
        "x",                           # too short
        "ok",                          # ok (2 chars)
        "x" * 31,                      # too long (>30)
        "tcp",                         # ok
    ])
    assert out == ["ok", "tcp"]


def test_normalize_tags_caps_at_max():
    many = [f"tag{i:02d}" for i in range(20)]
    out = _normalize_tags(many)
    assert len(out) == MAX_TAGS_PER_QUESTION
    assert out == [f"tag{i:02d}" for i in range(MAX_TAGS_PER_QUESTION)]


# --------------------------------------------------------------------------
# /api/results/tags/breakdown integration tests
# --------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "h.json"))
    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    import app.api.results as results_mod
    importlib.reload(results_mod)
    import app as app_mod
    importlib.reload(app_mod)
    db_mod.init_db()
    return app_mod.app.test_client()


def _seed(sid, questions, answers):
    from app.database import get_connection
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                question_count, difficulty, levels, questions,
                user_answers, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, "m", "src", "web", "cat", len(questions), "easy", "[]",
             json.dumps(questions, ensure_ascii=False),
             json.dumps(answers, ensure_ascii=False),
             "2024-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def test_breakdown_aggregates_across_sessions(client):
    _seed("s1",
          [
              {"id": "Q001", "question": "q1", "answer": "a",
               "tags": ["tcp/ip", "handshake"]},
              {"id": "Q002", "question": "q2", "answer": "b",
               "tags": ["tcp/ip", "header"]},
          ],
          {"Q001": "a", "Q002": "a"})  # 1 correct, 1 wrong
    _seed("s2",
          [
              {"id": "Q001", "question": "q3", "answer": "c",
               "tags": ["tcp/ip", "header"]},
          ],
          {"Q001": "c"})  # correct

    r = client.get("/api/results/tags/breakdown")
    assert r.status_code == 200
    by_tag = {t["tag"]: t for t in r.get_json()["tags"]}

    # tcp/ip appears in 3 questions (Q001-s1 right, Q002-s1 wrong, Q001-s2 right)
    assert by_tag["tcp/ip"]["total"] == 3
    assert by_tag["tcp/ip"]["correct"] == 2
    assert by_tag["tcp/ip"]["accuracy"] == 67

    # header appears in Q002-s1 (wrong) and Q001-s2 (right)
    assert by_tag["header"]["total"] == 2
    assert by_tag["header"]["correct"] == 1


def test_breakdown_skips_unanswered(client):
    _seed("s1",
          [{"id": "Q001", "question": "q", "answer": "a", "tags": ["foo"]},
           {"id": "Q002", "question": "q", "answer": "b", "tags": ["foo"]}],
          {"Q001": "a"})  # Q002 unanswered

    r = client.get("/api/results/tags/breakdown")
    by_tag = {t["tag"]: t for t in r.get_json()["tags"]}
    assert by_tag["foo"]["total"] == 1     # Q002 not counted
    assert by_tag["foo"]["correct"] == 1


def test_breakdown_skips_tagless_questions(client):
    _seed("s1",
          [{"id": "Q001", "question": "q", "answer": "a"}],  # no tags field
          {"Q001": "a"})

    r = client.get("/api/results/tags/breakdown")
    payload = r.get_json()
    assert payload["tags"] == []
    assert payload["weakest"] == []
    assert payload["most_attempted"] == []


def test_breakdown_weakest_requires_min_attempts(client):
    """A tag with only 1 question wrong = 0% should not be the
    "weakest" (statistical noise). Threshold = 3."""
    qs = []
    answers = {}
    # rare-fail: 1 wrong (0% but only n=1)
    qs.append({"id": "Q001", "question": "q", "answer": "a",
               "tags": ["rare-fail"]})
    answers["Q001"] = "b"
    # frequent-fail: 4 wrong of 4 (0% with n=4)
    for i in range(2, 6):
        qs.append({"id": f"Q{i:03d}", "question": "q",
                   "answer": "a", "tags": ["frequent-fail"]})
        answers[f"Q{i:03d}"] = "b"
    _seed("s1", qs, answers)

    r = client.get("/api/results/tags/breakdown")
    weakest = r.get_json()["weakest"]
    weakest_tags = [t["tag"] for t in weakest]
    assert "frequent-fail" in weakest_tags
    assert "rare-fail" not in weakest_tags  # below MIN_FOR_WEAKEST=3


def test_breakdown_dedupes_within_question(client):
    """If the same tag appears twice in one question's tag list (LLM
    glitch), it must count once."""
    _seed("s1",
          [{"id": "Q001", "question": "q", "answer": "a",
            "tags": ["tcp/ip", "TCP/IP", " tcp/ip "]}],
          {"Q001": "a"})

    r = client.get("/api/results/tags/breakdown")
    by_tag = {t["tag"]: t for t in r.get_json()["tags"]}
    assert by_tag["tcp/ip"]["total"] == 1
