"""Tests for /api/results/profile and /api/results/tags/backfill (SSE).

The backfill endpoint streams Server-Sent Events; the test exercises
the streamed body and verifies progress + done events arrive in order.
The LLM call inside is monkey-patched so the test is hermetic.
"""
from __future__ import annotations

import importlib
import json

import pytest


# --------------------------------------------------------------------------
# Fixture: hermetic Flask client + per-test SQLite
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


def _seed(sid, *, questions, answers, answered_at="2024-01-01T00:00:00Z",
          source_title="src"):
    from app.database import get_connection
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                question_count, difficulty, levels, questions,
                user_answers, generated_at, answered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, "m", source_title, "web", "cat", len(questions), "easy", "[]",
             json.dumps(questions, ensure_ascii=False),
             json.dumps(answers, ensure_ascii=False),
             answered_at, answered_at),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# /api/results/profile
# --------------------------------------------------------------------------
def test_profile_empty_when_no_data(client):
    r = client.get("/api/results/profile")
    assert r.status_code == 200
    p = r.get_json()
    assert p["overview"] == {
        "total_answered": 0, "total_correct": 0, "accuracy": 0,
        "active_days": 0, "last_active": "",
    }
    assert p["mastery"]["counts"] == {
        "master": 0, "proficient": 0, "familiar": 0, "beginner": 0,
    }
    assert p["weak_tags_with_examples"] == []
    assert p["recently_missed"] == []


def test_profile_overview_aggregates_across_sessions(client):
    _seed("s1",
          questions=[
              {"id": "Q001", "question": "q1", "answer": "a", "tags": ["foo"]},
              {"id": "Q002", "question": "q2", "answer": "b", "tags": ["foo"]},
          ],
          answers={"Q001": "a", "Q002": "a"},  # 1/2
          answered_at="2024-03-01T10:00:00Z")
    _seed("s2",
          questions=[
              {"id": "Q001", "question": "q3", "answer": "c", "tags": ["bar"]},
          ],
          answers={"Q001": "c"},
          answered_at="2024-03-02T10:00:00Z")

    r = client.get("/api/results/profile")
    o = r.get_json()["overview"]
    assert o["total_answered"] == 3
    assert o["total_correct"] == 2
    assert o["accuracy"] == 67
    assert o["active_days"] == 2  # 03-01, 03-02
    assert o["last_active"] == "2024-03-02T10:00:00Z"


def test_profile_mastery_tiers_classify_correctly(client):
    """50/70/90 のしきい値で正しく振り分けられるか。"""
    questions = [
        # tag-master: 10/10 = 100%
        *[{"id": f"M{i:03d}", "question": "q", "answer": "a",
           "tags": ["tag-master"]} for i in range(10)],
        # tag-proficient: 8/10 = 80%
        *[{"id": f"P{i:03d}", "question": "q", "answer": "a",
           "tags": ["tag-proficient"]} for i in range(10)],
        # tag-familiar: 6/10 = 60%
        *[{"id": f"F{i:03d}", "question": "q", "answer": "a",
           "tags": ["tag-familiar"]} for i in range(10)],
        # tag-beginner: 2/10 = 20%
        *[{"id": f"B{i:03d}", "question": "q", "answer": "a",
           "tags": ["tag-beginner"]} for i in range(10)],
    ]
    answers = {}
    for i in range(10):
        answers[f"M{i:03d}"] = "a"  # all correct
    for i in range(8):
        answers[f"P{i:03d}"] = "a"
    for i in range(8, 10):
        answers[f"P{i:03d}"] = "b"  # 2 wrong → 8/10
    for i in range(6):
        answers[f"F{i:03d}"] = "a"
    for i in range(6, 10):
        answers[f"F{i:03d}"] = "b"
    for i in range(2):
        answers[f"B{i:03d}"] = "a"
    for i in range(2, 10):
        answers[f"B{i:03d}"] = "b"

    _seed("s1", questions=questions, answers=answers)

    r = client.get("/api/results/profile")
    m = r.get_json()["mastery"]
    by_tag = {}
    for tier in ("master", "proficient", "familiar", "beginner"):
        for t in m[tier]:
            by_tag[t["tag"]] = (tier, t["accuracy"])

    assert by_tag["tag-master"][0]     == "master"
    assert by_tag["tag-proficient"][0] == "proficient"
    assert by_tag["tag-familiar"][0]   == "familiar"
    assert by_tag["tag-beginner"][0]   == "beginner"
    assert m["counts"]["master"]     == 1
    assert m["counts"]["proficient"] == 1
    assert m["counts"]["familiar"]   == 1
    assert m["counts"]["beginner"]   == 1


def test_profile_weak_tags_skip_n1_noise(client):
    """1 attempt は弱点リストに入らない (statistical noise 除外)。"""
    _seed("s1",
          questions=[
              {"id": "Q001", "question": "q", "answer": "a", "tags": ["n1-fail"]},
              # n2-fail: 2 attempts both wrong
              {"id": "Q002", "question": "q", "answer": "a", "tags": ["n2-fail"]},
              {"id": "Q003", "question": "q", "answer": "a", "tags": ["n2-fail"]},
          ],
          answers={"Q001": "b", "Q002": "b", "Q003": "b"})

    r = client.get("/api/results/profile")
    weak_tags = [t["tag"] for t in r.get_json()["weak_tags_with_examples"]]
    assert "n1-fail" not in weak_tags  # only 1 attempt
    assert "n2-fail" in weak_tags


def test_profile_recently_missed_sorted_by_answered_at(client):
    _seed("old", source_title="old-src",
          questions=[{"id": "Q001", "question": "q-old",
                      "answer": "a", "tags": []}],
          answers={"Q001": "b"},
          answered_at="2024-01-01T00:00:00Z")
    _seed("new", source_title="new-src",
          questions=[{"id": "Q001", "question": "q-new",
                      "answer": "a", "tags": []}],
          answers={"Q001": "b"},
          answered_at="2024-12-31T23:59:59Z")

    r = client.get("/api/results/profile")
    missed = r.get_json()["recently_missed"]
    assert len(missed) == 2
    assert missed[0]["session_id"] == "new"  # newer first
    assert missed[0]["question"]   == "q-new"
    assert missed[1]["session_id"] == "old"


# --------------------------------------------------------------------------
# /api/results/tags/backfill (SSE)
# --------------------------------------------------------------------------
def test_backfill_skips_already_tagged(client, monkeypatch):
    _seed("s1",
          questions=[
              {"id": "Q001", "question": "q", "answer": "a",
               "tags": ["existing"]},
          ],
          answers={"Q001": "a"})

    # No LLM should be called since the only question already has tags
    from app.api import results as results_mod
    def boom(*args, **kwargs):
        raise AssertionError("tag_question_only must not be called")
    monkeypatch.setattr(results_mod._quiz_service, "tag_question_only", boom)
    monkeypatch.setattr(
        results_mod._quiz_service, "_resolve_model", lambda m: m,
    )

    r = client.post("/api/results/tags/backfill", json={"model": "m"})
    assert r.status_code == 200
    body = r.data.decode()
    assert "\"total\": 0" in body
    assert "event: done" in body


def test_backfill_streams_progress_and_persists_tags(client, monkeypatch):
    _seed("s1",
          questions=[
              {"id": "Q001", "question": "q1", "answer": "a"},  # no tags
              {"id": "Q002", "question": "q2", "answer": "b"},  # no tags
          ],
          answers={"Q001": "a", "Q002": "b"})
    _seed("s2",
          questions=[
              {"id": "Q001", "question": "q3", "answer": "a"},  # no tags
          ],
          answers={"Q001": "a"})

    from app.api import results as results_mod
    monkeypatch.setattr(
        results_mod._quiz_service, "_resolve_model", lambda m: m,
    )
    # Deterministic LLM: returns ["fixed-tag"] for any q
    monkeypatch.setattr(
        results_mod._quiz_service, "tag_question_only",
        lambda q, model, **kw: ["fixed-tag"],
    )

    r = client.post("/api/results/tags/backfill", json={"model": "m"})
    assert r.status_code == 200
    body = r.data.decode()
    assert "event: start" in body
    assert "\"total\": 3" in body  # 3 untagged
    assert body.count("event: tagged") == 3
    assert "event: done" in body
    assert "\"tagged\": 3" in body
    assert "\"errors\": 0" in body

    # Verify persistence — sessions should now have tags applied
    from app.database import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT session_id, questions FROM quiz_sessions ORDER BY session_id"
        ).fetchall()
    finally:
        conn.close()
    by_sid = {row["session_id"]: json.loads(row["questions"]) for row in rows}
    for sid, qs in by_sid.items():
        for q in qs:
            assert q["tags"] == ["fixed-tag"], (sid, q)


def test_backfill_continues_past_individual_errors(client, monkeypatch):
    _seed("s1",
          questions=[
              {"id": "Q001", "question": "q1", "answer": "a"},
              {"id": "Q002", "question": "q2", "answer": "b"},
              {"id": "Q003", "question": "q3", "answer": "c"},
          ],
          answers={"Q001": "a", "Q002": "b", "Q003": "c"})

    from app.api import results as results_mod
    monkeypatch.setattr(
        results_mod._quiz_service, "_resolve_model", lambda m: m,
    )

    call_count = {"n": 0}
    def flaky(q, model, **kw):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated LLM error")
        return ["ok-tag"]

    monkeypatch.setattr(
        results_mod._quiz_service, "tag_question_only", flaky,
    )

    r = client.post("/api/results/tags/backfill", json={"model": "m"})
    body = r.data.decode()
    assert "\"tagged\": 2" in body
    assert "\"errors\": 1" in body


def test_backfill_requires_model(client):
    r = client.post("/api/results/tags/backfill", json={})
    assert r.status_code == 400


def test_backfill_validates_model_charset(client):
    r = client.post("/api/results/tags/backfill",
                    json={"model": "bad model;rm -rf /"})
    assert r.status_code == 400
