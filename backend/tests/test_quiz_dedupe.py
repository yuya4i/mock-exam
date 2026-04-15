"""
Duplicate-question detection in QuizService (generate_incremental and
generate_single_question).

The LLM sometimes echoes a question body that's already in the session
— either from the live prompt's "previous topics" block not being
strong enough, or from deterministic decoding. A post-parse compare
rejects the dupe and retries within a small attempt budget.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.services.quiz_service import QuizService, _normalize_question_text


def _q_json(body: str, qid: str = "Q001", topic: str = "t") -> str:
    return json.dumps({
        "id": qid, "level": "K2", "topic": topic,
        "question": body,
        "diagram": "",
        "choices": {"a": "a", "b": "b", "c": "c", "d": "d"},
        "answer": "a", "explanation": "x", "source_hint": "",
    }, ensure_ascii=False)


# ------------------------------------------------------------------
# Normalizer
# ------------------------------------------------------------------
def test_normalize_strips_whitespace_and_lowercases():
    a = _normalize_question_text("  Hello World ")
    b = _normalize_question_text("hello  world")
    assert a == b == "hello world"


def test_normalize_drops_trailing_punct():
    a = _normalize_question_text("これは？")
    b = _normalize_question_text("これは")
    assert a == b


def test_normalize_empty_returns_empty():
    assert _normalize_question_text(None) == ""
    assert _normalize_question_text("") == ""


# ------------------------------------------------------------------
# generate_incremental dedupe
# ------------------------------------------------------------------
def test_incremental_rejects_dupe_and_retries_with_fresh_text():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "t", "content": "c", "source": "s", "type": "x",
        "depth": 1, "doc_types": [], "page_count": 1, "pages": [],
    }
    svc.ollama = MagicMock()
    # First LLM call returns a dupe; second returns a unique body.
    svc.ollama.chat.side_effect = [
        _q_json("これは重複する問題です"),
        _q_json("別の観点から出題された問題です"),
    ]

    events = list(svc.generate_incremental(
        source="x", model="m", count=1,
        exclude_question_texts=["これは重複する問題です"],
    ))

    qs = [d for (t, d) in events if t == "question"]
    errs = [d for (t, d) in events if t == "question_error"]
    assert len(qs) == 1, events
    assert len(errs) == 0
    assert qs[0]["question"] == "別の観点から出題された問題です"
    # Two ollama calls: one rejected, one accepted.
    assert svc.ollama.chat.call_count == 2


def test_incremental_gives_up_after_three_attempts_all_duplicate():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "t", "content": "c", "source": "s", "type": "x",
        "depth": 1, "doc_types": [], "page_count": 1, "pages": [],
    }
    svc.ollama = MagicMock()
    svc.ollama.chat.return_value = _q_json("毎回同じ問題")

    events = list(svc.generate_incremental(
        source="x", model="m", count=1,
        exclude_question_texts=["毎回同じ問題"],
    ))

    qs = [d for (t, d) in events if t == "question"]
    errs = [d for (t, d) in events if t == "question_error"]
    assert len(qs) == 0
    assert len(errs) == 1
    assert svc.ollama.chat.call_count == 3


# ------------------------------------------------------------------
# qnum_start
# ------------------------------------------------------------------
def test_incremental_respects_qnum_start():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "t", "content": "c", "source": "s", "type": "x",
        "depth": 1, "doc_types": [], "page_count": 1, "pages": [],
    }
    svc.ollama = MagicMock()
    # Return valid unique questions each call.
    svc.ollama.chat.side_effect = [
        _q_json(f"問題 {i}", qid=f"Q{i:03d}") for i in range(11, 14)
    ]

    events = list(svc.generate_incremental(
        source="x", model="m", count=3, qnum_start=11,
    ))

    progress_events = [d for (t, d) in events if t == "progress"]
    # First progress event should show qnum=11 as the start of the new run.
    # (The SINGLE_Q_TEMPLATE prompt is built with qnum=11, 12, 13 — the
    #  LLM is instructed to emit Q011/Q012/Q013 as ids.)
    assert progress_events[0]["current"] == 11
    assert progress_events[-1]["current"] == 13


# ------------------------------------------------------------------
# generate_single_question dedupe
# ------------------------------------------------------------------
def test_single_question_retries_until_non_duplicate():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "t", "content": "c", "source": "s", "type": "x",
        "depth": 1, "doc_types": [], "page_count": 1, "pages": [],
    }
    svc.ollama = MagicMock()
    svc.ollama.chat.side_effect = [
        _q_json("重複 A"),
        _q_json("重複 B"),   # also in exclude list
        _q_json("新しい観点の問題"),
    ]

    q = svc.generate_single_question(
        source="x", model="m",
        exclude_question_texts=["重複 A", "重複 B"],
    )
    assert q is not None
    assert q["question"] == "新しい観点の問題"
    assert svc.ollama.chat.call_count == 3


def test_single_question_returns_none_when_all_duplicates():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "t", "content": "c", "source": "s", "type": "x",
        "depth": 1, "doc_types": [], "page_count": 1, "pages": [],
    }
    svc.ollama = MagicMock()
    svc.ollama.chat.return_value = _q_json("ずっと重複")

    q = svc.generate_single_question(
        source="x", model="m",
        exclude_question_texts=["ずっと重複"],
    )
    assert q is None
    assert svc.ollama.chat.call_count == 3
