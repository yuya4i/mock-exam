"""Tests for the atomic-append save path (BACKEND-2 / Red Team P0).

Two concurrent ``+N問`` clicks from the user (or two browser tabs) used
to race: each request snapshotted ``existing_questions`` before
generation, so each ``_save_quiz_session`` call would write
``snapshot + its own new`` and the second commit would discard the
first's additions.

The fix moves the question-merge inside ``_save_quiz_session`` and
guards it with ``BEGIN IMMEDIATE``; the save now re-reads the canonical
current questions, renumbers the new batch to follow that count, and
appends — so two sequential saves with the same snapshot still produce
``base + A_new + B_new``.

These tests don't actually use threads (SQLite serialization makes the
race deterministic when invoked sequentially with stale snapshots), so
they're fast and reproducible.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def app_modules(tmp_path, monkeypatch):
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
    return {"db": db_mod, "quiz": quiz_mod}


def _seed_session(db_mod, sid, n_base):
    base = [
        {"id": f"Q{i + 1:03d}", "question": f"Base Q{i + 1}", "topic": "base"}
        for i in range(n_base)
    ]
    conn = db_mod.get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                question_count, difficulty, levels, questions, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, "test-model", "src", "web", "cat",
             n_base, "easy", "[]",
             json.dumps(base, ensure_ascii=False),
             "2024-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    return base


def _read_questions(db_mod, sid):
    conn = db_mod.get_connection()
    try:
        row = conn.execute(
            "SELECT questions FROM quiz_sessions WHERE session_id = ?",
            (sid,),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row["questions"]) if row else None


def test_two_appends_with_stale_snapshots_preserve_both(app_modules):
    """The race: A and B both snapshotted [Q001..Q020], both generated
    5 new with IDs Q021..Q025 (collision), both call save with their
    own snapshot+new. The atomic fix must result in 30 total questions
    (base + A_new + B_new), not 25 (B overwriting A)."""
    db_mod = app_modules["db"]
    quiz_mod = app_modules["quiz"]

    sid = "sess-race-001"
    base = _seed_session(db_mod, sid, n_base=20)

    new_a = [
        {"id": f"Q{20 + i + 1:03d}", "question": f"A new {i}", "topic": "ta"}
        for i in range(5)
    ]
    new_b = [
        {"id": f"Q{20 + i + 1:03d}", "question": f"B new {i}", "topic": "tb"}
        for i in range(5)
    ]

    # Simulate request A: snapshot=20, generated 5 new. The event_stream
    # would have built data["questions"] = snapshot + new_a.
    quiz_mod._save_quiz_session(
        {
            "session_id": sid,
            "questions": list(base) + new_a,
            "generated_at": "2024-01-01T01:00:00Z",
            "source_info": {},
            "model": "test-model",
        },
        {
            "append_to_session_id": sid,
            "levels": [],
            "_append_new_questions": new_a,
        },
    )

    # Simulate request B (stale snapshot — also saw 20 base) finishing
    # second: snapshot+new_b.
    quiz_mod._save_quiz_session(
        {
            "session_id": sid,
            "questions": list(base) + new_b,
            "generated_at": "2024-01-01T01:00:01Z",
            "source_info": {},
            "model": "test-model",
        },
        {
            "append_to_session_id": sid,
            "levels": [],
            "_append_new_questions": new_b,
        },
    )

    final = _read_questions(db_mod, sid)
    assert final is not None, "session row vanished"
    assert len(final) == 30, (
        f"BACKEND-2: expected base+A+B=30 questions, got {len(final)} "
        f"(snapshot overwrite race)"
    )

    # IDs must be unique and sequential Q001..Q030 after renumber
    ids = [q["id"] for q in final]
    assert ids == [f"Q{i + 1:03d}" for i in range(30)], (
        f"IDs not sequential after atomic merge: {ids}"
    )

    # Body content from BOTH new batches must be present (no overwrite)
    bodies = [q["question"] for q in final]
    assert any("A new" in b for b in bodies), "A's batch was overwritten"
    assert any("B new" in b for b in bodies), "B's batch was overwritten"


def test_append_to_missing_session_is_noop(app_modules):
    """If the session was concurrently deleted between request start
    and save, we must not 500 and must not magically resurrect it."""
    quiz_mod = app_modules["quiz"]
    db_mod = app_modules["db"]

    quiz_mod._save_quiz_session(
        {
            "session_id": "sess-does-not-exist",
            "questions": [{"id": "Q001", "question": "x", "topic": "t"}],
            "generated_at": "2024-01-01T00:00:00Z",
            "source_info": {},
            "model": "test-model",
        },
        {
            "append_to_session_id": "sess-does-not-exist",
            "levels": [],
            "_append_new_questions": [{"id": "Q001", "question": "x", "topic": "t"}],
        },
    )

    final = _read_questions(db_mod, "sess-does-not-exist")
    assert final is None, "deleted session should not be resurrected by append"


def test_append_renumbers_new_to_follow_actual_count(app_modules):
    """Even if the LLM produces colliding IDs, the save must rewrite
    them to be sequential after the current count."""
    quiz_mod = app_modules["quiz"]
    db_mod = app_modules["db"]

    sid = "sess-renum-001"
    base = _seed_session(db_mod, sid, n_base=10)

    # New batch with garbage / colliding IDs
    new = [
        {"id": "Q005", "question": "junk id 1", "topic": "x"},  # would collide
        {"id": "QQQ",  "question": "junk id 2", "topic": "x"},  # malformed
        {"id": "Q011", "question": "ok id",     "topic": "x"},  # accidentally right
    ]
    quiz_mod._save_quiz_session(
        {
            "session_id": sid,
            "questions": list(base) + new,
            "generated_at": "2024-01-01T01:00:00Z",
            "source_info": {},
            "model": "test-model",
        },
        {
            "append_to_session_id": sid,
            "levels": [],
            "_append_new_questions": new,
        },
    )

    final = _read_questions(db_mod, sid)
    assert final is not None
    assert len(final) == 13
    ids = [q["id"] for q in final]
    assert ids == [f"Q{i + 1:03d}" for i in range(13)], f"got {ids}"
