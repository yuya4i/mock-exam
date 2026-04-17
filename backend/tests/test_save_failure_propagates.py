"""Tests that a failed save during /api/quiz/generate surfaces as an
SSE error event, instead of being silently logged after the FE has
already received "done" (BACKEND-7 + BACKEND-11).

The previous flow was:
    yield done → _save_quiz_session(...) → log.warning(...) on error
which left the user thinking the session was saved when it wasn't.
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
    return {"db": db_mod, "quiz": quiz_mod, "app": app_mod}


def _parse_sse(body: bytes):
    """Very small SSE parser: returns list of (event, data_dict)."""
    out = []
    text = body.decode("utf-8")
    for chunk in text.split("\n\n"):
        if not chunk.strip():
            continue
        ev, dat = None, None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                dat = line[len("data: "):]
        if ev and dat:
            try:
                out.append((ev, json.loads(dat)))
            except json.JSONDecodeError:
                out.append((ev, {"raw": dat}))
    return out


def test_save_failure_emits_sse_error_after_questions(app_modules, monkeypatch):
    """When the save raises, the stream should NOT terminate with a
    bare done — it should emit an error event so the FE knows the
    quiz wasn't persisted."""
    quiz_mod = app_modules["quiz"]
    app_mod = app_modules["app"]

    def fake_incremental(**kwargs):
        yield ("source_info", {"session_id": "sess-fail",
                               "title": "t", "source": "s", "type": "x",
                               "depth": 1, "doc_types": [], "page_count": 1})
        yield ("question", {"id": "Q001", "question": "x"})
        yield ("done", {
            "session_id": "sess-fail",
            "generated_at": "2026-04-15T00:00:00Z",
            "model": "test-model",
            "question_count": 1,
            "questions": [{
                "id": "Q001", "question": "x", "topic": "t", "level": "K2",
                "choices": {"a": "1", "b": "2"}, "answer": "a",
            }],
            "source_info": {},
        })

    monkeypatch.setattr(
        quiz_mod._quiz_service, "generate_incremental", fake_incremental,
    )
    # Force a save failure
    def boom(*args, **kwargs):
        raise RuntimeError("simulated SQLite failure")
    monkeypatch.setattr(quiz_mod, "_save_quiz_session", boom)

    client = app_mod.app.test_client()
    r = client.post("/api/quiz/generate", json={
        "source": "https://example.com",
        "model": "dummy",
        "count": 1,
    })
    events = _parse_sse(r.data)
    types = [e for e, _ in events]
    # The done event must NOT be the last one when save failed —
    # an error event has to follow to inform the FE.
    assert "error" in types, (
        f"BACKEND-11: save failure should emit SSE error; types={types}"
    )
    err_payload = next(d for e, d in events if e == "error")
    assert "保存" in err_payload.get("message", "") or "save" in err_payload.get(
        "message", "").lower(), err_payload


def test_save_success_still_emits_done_normally(app_modules, monkeypatch):
    """Sanity: when save succeeds, the "done" event must arrive (no
    spurious error)."""
    quiz_mod = app_modules["quiz"]
    app_mod = app_modules["app"]

    def fake_incremental(**kwargs):
        yield ("source_info", {"session_id": "sess-ok",
                               "title": "t", "source": "s", "type": "x",
                               "depth": 1, "doc_types": [], "page_count": 1})
        yield ("done", {
            "session_id": "sess-ok",
            "generated_at": "2026-04-15T00:00:00Z",
            "model": "test-model",
            "question_count": 1,
            "questions": [{
                "id": "Q001", "question": "x", "topic": "t", "level": "K2",
                "choices": {"a": "1", "b": "2"}, "answer": "a",
            }],
            "source_info": {},
        })

    monkeypatch.setattr(
        quiz_mod._quiz_service, "generate_incremental", fake_incremental,
    )

    client = app_mod.app.test_client()
    r = client.post("/api/quiz/generate", json={
        "source": "https://example.com",
        "model": "dummy",
        "count": 1,
    })
    events = _parse_sse(r.data)
    types = [e for e, _ in events]
    assert "done" in types
    assert "error" not in types
