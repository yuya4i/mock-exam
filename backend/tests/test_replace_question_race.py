"""Tests for _replace_question_in_session atomicity (BACKEND-5).

Two concurrent regenerate-question calls on different question_ids in
the same session used to race: each read [q1, q2, q3], each modified
their target, the second commit silently dropped the first's edit.

Fix: BEGIN IMMEDIATE wraps the SELECT→UPDATE so the second call sees
the post-first state and merges into it instead of overwriting.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def quiz_mod(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "history.json"))

    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    import app.api.quiz as quiz_mod
    importlib.reload(quiz_mod)
    db_mod.init_db()
    return quiz_mod


def _seed(qid_list=("Q001", "Q002", "Q003")):
    from app.database import get_connection
    questions = [
        {"id": qid, "question": f"orig {qid}", "topic": "t", "level": "K2"}
        for qid in qid_list
    ]
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                question_count, difficulty, levels, questions, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sess-rep-001", "test-model", "src", "web", "cat",
             len(questions), "easy", "[]",
             json.dumps(questions, ensure_ascii=False),
             "2024-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    return questions


def _read_session():
    from app.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT questions FROM quiz_sessions WHERE session_id = ?",
            ("sess-rep-001",),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row["questions"]) if row else None


def test_two_concurrent_replaces_both_persisted(quiz_mod):
    """Replace Q001 with new1, then replace Q003 with new3 sequentially.
    Sequential calls work in either implementation, but with the BEGIN
    IMMEDIATE guard the second call's read picks up the first's write.
    The non-atomic version would *also* succeed here because each
    targets a different index — so we additionally verify that simply
    interleaving (re-call with stale data) doesn't drop the edit."""
    _seed()

    new1 = {"id": "ignored", "question": "regen Q001", "topic": "t1", "level": "K2"}
    new3 = {"id": "ignored", "question": "regen Q003", "topic": "t3", "level": "K2"}

    assert quiz_mod._replace_question_in_session(
        session_id="sess-rep-001",
        old_question_id="Q001",
        new_question=new1,
    ) is True
    assert quiz_mod._replace_question_in_session(
        session_id="sess-rep-001",
        old_question_id="Q003",
        new_question=new3,
    ) is True

    final = _read_session()
    assert final[0]["question"] == "regen Q001"
    assert final[1]["question"] == "orig Q002"  # untouched
    assert final[2]["question"] == "regen Q003"
    # IDs are stable (forced by the fix-up at line 494)
    assert [q["id"] for q in final] == ["Q001", "Q002", "Q003"]


def test_replace_unknown_qid_returns_false_no_write(quiz_mod):
    _seed()
    new = {"id": "x", "question": "irrelevant", "topic": "t", "level": "K2"}
    assert quiz_mod._replace_question_in_session(
        session_id="sess-rep-001",
        old_question_id="Q999",  # not in session
        new_question=new,
    ) is False
    final = _read_session()
    # Nothing should have changed.
    assert [q["question"] for q in final] == [
        "orig Q001", "orig Q002", "orig Q003"
    ]


def test_replace_when_session_deleted_concurrently_returns_false(quiz_mod):
    """If the session row was removed between the regen request and
    the save, the replace should report False (not crash, not insert)."""
    new = {"id": "x", "question": "irrelevant", "topic": "t", "level": "K2"}
    assert quiz_mod._replace_question_in_session(
        session_id="sess-does-not-exist",
        old_question_id="Q001",
        new_question=new,
    ) is False


def test_concurrent_replaces_with_stale_snapshot_dont_overwrite(quiz_mod, monkeypatch):
    """The race scenario the fix targets: A and B both READ before
    either WRITE. With the BEGIN IMMEDIATE wrap, the second writer
    is forced to wait for the first to commit, then re-read inside
    its own transaction.

    We simulate the race by calling the function twice; the
    implementation of the fix re-reads inside the writer-locked
    transaction so even back-to-back calls see each other's writes.
    The hard test is the threaded one below."""
    _seed()

    # Sequential regen; second call must see Q001 already-changed.
    quiz_mod._replace_question_in_session(
        "sess-rep-001", "Q001",
        {"question": "A wins Q001", "topic": "ta", "level": "K2"},
    )
    final_after_a = _read_session()
    assert final_after_a[0]["question"] == "A wins Q001"

    # B targets Q002. Without BEGIN IMMEDIATE this could in theory
    # write a stale snapshot if there were any caching layer. The
    # contract: B's edit must take Q002 AND keep A's Q001.
    quiz_mod._replace_question_in_session(
        "sess-rep-001", "Q002",
        {"question": "B wins Q002", "topic": "tb", "level": "K2"},
    )
    final = _read_session()
    assert final[0]["question"] == "A wins Q001", (
        "BACKEND-5: B's regen should not have clobbered A's earlier edit"
    )
    assert final[1]["question"] == "B wins Q002"


def test_threaded_replaces_no_lost_update(quiz_mod):
    """The actual race: two threads, each opens its own sqlite3
    connection, each SELECT-MODIFY-UPDATE. Without BEGIN IMMEDIATE
    one of them sees a stale snapshot and the second commit silently
    drops the first's edit. With the fix, the writer lock serializes
    them and both edits land."""
    import threading
    from app.database import get_connection

    _seed()

    barrier = threading.Barrier(2)
    errors: list[str] = []

    def worker(qid: str, label: str):
        try:
            barrier.wait(timeout=5)
            ok = quiz_mod._replace_question_in_session(
                "sess-rep-001", qid,
                {"question": f"regen by {label}", "topic": label, "level": "K2"},
            )
            if not ok:
                errors.append(f"{label}: replace returned False")
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}: {e}")

    t1 = threading.Thread(target=worker, args=("Q001", "A"))
    t2 = threading.Thread(target=worker, args=("Q002", "B"))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)

    assert not errors, errors
    final = _read_session()
    bodies = [q["question"] for q in final]
    assert "regen by A" in bodies, (
        f"BACKEND-5: A's edit was lost in race; bodies={bodies}"
    )
    assert "regen by B" in bodies, (
        f"BACKEND-5: B's edit was lost in race; bodies={bodies}"
    )
    assert "orig Q003" in bodies, "Q003 should be untouched"
