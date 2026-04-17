"""Tests for SEC-5 session_id charset validation."""
from __future__ import annotations

import importlib

import pytest

from app.api._schemas import is_valid_session_id


@pytest.mark.parametrize("sid, ok", [
    ("a", True),
    ("ABC123_-", True),
    ("a" * 64, True),
    ("550e8400-e29b-41d4-a716-446655440000", True),  # uuid4
    ("", False),
    ("a" * 65, False),
    ("ab/cd", False),    # path separator
    ("ab cd", False),    # space
    ("ab.cd", False),    # dot
    ("../etc", False),   # path traversal
    ("'; DROP--", False),
    ("日本語", False),
    (None, False),
    (123, False),
])
def test_is_valid_session_id(sid, ok):
    assert is_valid_session_id(sid) is ok


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "h.json"))
    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    import app as app_mod
    importlib.reload(app_mod)
    db_mod.init_db()
    return app_mod.app.test_client()


def test_get_result_with_bad_session_id_400(client):
    r = client.get("/api/results/'; DROP TABLE--")
    assert r.status_code == 400


def test_get_result_with_valid_but_unknown_id_404(client):
    r = client.get("/api/results/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert r.status_code == 404


def test_save_answers_with_bad_session_id_400(client):
    r = client.post(
        "/api/results/ab cd/answers",
        json={"answers": {"Q001": "a"}, "score_correct": 0, "score_total": 0},
    )
    assert r.status_code == 400


def test_delete_with_bad_session_id_400(client):
    r = client.delete("/api/results/" + "x" * 65)
    assert r.status_code == 400


def test_quiz_generate_append_with_bad_session_id_400(client):
    r = client.post("/api/quiz/generate", json={
        "source": "https://example.com",
        "model": "dummy",
        "count": 1,
        "append_to_session_id": "../../etc/passwd",
    })
    assert r.status_code == 400
