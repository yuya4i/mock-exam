"""Tests for the exam_type (JSTQB / IPA 等) analytics dimension:
- quiz_sessions.exam_type column + migration
- GET /api/results/exam-types summary
- ?exam_type= filter on results / categories / breakdown / tags / profile
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
    import app.api.results as results_mod
    importlib.reload(results_mod)
    import app as app_mod
    importlib.reload(app_mod)
    db_mod.init_db()
    return app_mod.app.test_client()


def _seed(exam_type, category, qids_correct):
    """qids_correct: list of (qid, answer, given) tuples."""
    from app.database import get_connection
    questions = [
        {"id": qid, "level": "K2", "topic": category, "tags": [category.lower()],
         "question": f"{category} q {qid}", "choices": {"a": "x", "b": "y"},
         "answer": ans}
        for (qid, ans, _given) in qids_correct
    ]
    answers = {qid: given for (qid, _ans, given) in qids_correct}
    correct = sum(1 for (_q, a, g) in qids_correct if a == g)
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO quiz_sessions
               (session_id, model, source_title, source_type, category,
                exam_type, question_count, difficulty, levels, questions,
                user_answers, score_correct, score_total, generated_at, answered_at)
               VALUES (?, 'm', ?, 'demo', ?, ?, ?, 'medium', '["K2"]', ?, ?, ?, ?, ?, ?)""",
            (f"s-{exam_type}-{category}".replace(" ", "_"),
             f"{exam_type} {category}", category, exam_type,
             len(questions), json.dumps(questions, ensure_ascii=False),
             json.dumps(answers, ensure_ascii=False),
             correct, len(questions),
             "2026-06-01T00:00:00Z", "2026-06-01T00:30:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _setup_two_types():
    # JSTQB FL: 3/4 correct (75%)
    _seed("JSTQB FL", "テスト技法",
          [("Q001", "a", "a"), ("Q002", "a", "a"),
           ("Q003", "a", "a"), ("Q004", "a", "b")])
    # IPA SC: 1/4 correct (25%)
    _seed("IPA SC", "暗号",
          [("Q001", "a", "a"), ("Q002", "a", "b"),
           ("Q003", "a", "b"), ("Q004", "a", "b")])


def test_exam_types_summary(client):
    _setup_two_types()
    r = client.get("/api/results/exam-types")
    assert r.status_code == 200
    by = {e["exam_type"]: e for e in r.get_json()["exam_types"]}
    assert by["JSTQB FL"]["accuracy"] == 75
    assert by["JSTQB FL"]["total_answered"] == 4
    assert by["IPA SC"]["accuracy"] == 25
    assert by["JSTQB FL"]["session_count"] == 1


def test_profile_filtered_by_exam_type(client):
    _setup_two_types()
    # All
    allp = client.get("/api/results/profile").get_json()["overview"]
    assert allp["total_answered"] == 8
    assert allp["total_correct"] == 4  # 3 + 1
    # JSTQB FL only
    fl = client.get("/api/results/profile?exam_type=JSTQB FL").get_json()["overview"]
    assert fl["total_answered"] == 4
    assert fl["total_correct"] == 3
    assert fl["accuracy"] == 75
    # IPA SC only
    sc = client.get("/api/results/profile?exam_type=IPA SC").get_json()["overview"]
    assert sc["total_correct"] == 1
    assert sc["accuracy"] == 25


def test_results_list_filtered_and_carries_exam_type(client):
    _setup_two_types()
    allr = client.get("/api/results").get_json()["sessions"]
    assert len(allr) == 2
    assert {s["exam_type"] for s in allr} == {"JSTQB FL", "IPA SC"}
    only = client.get("/api/results?exam_type=JSTQB FL").get_json()["sessions"]
    assert len(only) == 1
    assert only[0]["exam_type"] == "JSTQB FL"


def test_categories_filtered_by_exam_type(client):
    _setup_two_types()
    only = client.get("/api/results/categories?exam_type=IPA SC").get_json()["categories"]
    cats = {c["category"] for c in only}
    assert cats == {"暗号"}  # テスト技法 (JSTQB) は除外


def test_exam_type_all_keyword_means_unfiltered(client):
    _setup_two_types()
    p = client.get("/api/results/profile?exam_type=all").get_json()["overview"]
    assert p["total_answered"] == 8  # "all" treated as no filter


def test_unknown_exam_type_returns_empty(client):
    _setup_two_types()
    p = client.get("/api/results/profile?exam_type=NONEXISTENT").get_json()["overview"]
    assert p["total_answered"] == 0
    assert p["accuracy"] == 0
