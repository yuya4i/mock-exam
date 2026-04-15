"""
Covers the perf path where saved-session regeneration reuses stored
document content instead of re-scraping (feature/regen-use-stored-content).

Strategy
--------
Stub the outbound surfaces at the ``QuizService`` instance level:
  - ``self.content.fetch``   must NOT be called when source_info_override
                             is supplied.
  - ``self.ollama.chat``     returns a canned JSON question string.

This locks the contract "append-mode and single-question regen never
touch ContentService when a document row exists for the session".
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.services.quiz_service import QuizService


FAKE_QUESTION_JSON = """\
{"id":"Q001","level":"K2","topic":"テスト","question":"問題?",
 "diagram":"","choices":{"a":"a","b":"b","c":"c","d":"d"},
 "answer":"a","explanation":"説明。","source_hint":"src"}
"""


def _make_override(content: str = "stored content body") -> dict:
    return {
        "title":       "Cached Doc",
        "content":     content,
        "source":      "https://example.com/cached",
        "type":        "url_deep",
        "depth":       1,
        "doc_types":   ["table"],
        "page_count":  1,
        "pages":       [],
        "document_id": 42,
    }


# ------------------------------------------------------------------
# generate_incremental
# ------------------------------------------------------------------
def test_incremental_with_override_skips_content_fetch():
    svc = QuizService()
    svc.content = MagicMock()   # would raise if fetch() is called
    svc.content.fetch.side_effect = AssertionError("fetch must not run")
    svc.ollama = MagicMock()
    svc.ollama.chat.return_value = FAKE_QUESTION_JSON

    override = _make_override()
    events = list(svc.generate_incremental(
        source="ignored://should-not-be-used",
        model="dummy",
        count=1,
        source_info_override=override,
    ))

    svc.content.fetch.assert_not_called()

    # The streamed source_info must reflect the override, not a scrape.
    source_info_events = [d for (t, d) in events if t == "source_info"]
    assert len(source_info_events) == 1
    assert source_info_events[0]["title"] == "Cached Doc"
    assert source_info_events[0]["source"] == "https://example.com/cached"
    assert source_info_events[0]["document_id"] == 42

    done_events = [d for (t, d) in events if t == "done"]
    assert len(done_events) == 1
    assert done_events[0]["question_count"] == 1


def test_incremental_without_override_still_calls_fetch():
    """Regression: omitting the override keeps the original scrape path."""
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "Live", "content": "live content", "source": "https://live",
        "type": "url_deep", "depth": 1, "doc_types": ["table"],
        "page_count": 1, "pages": [], "document_id": 99,
    }
    svc.ollama = MagicMock()
    svc.ollama.chat.return_value = FAKE_QUESTION_JSON

    list(svc.generate_incremental(source="https://live", model="x", count=1))

    svc.content.fetch.assert_called_once()


# ------------------------------------------------------------------
# generate_single_question
# ------------------------------------------------------------------
def test_single_question_with_override_skips_content_fetch():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.side_effect = AssertionError("fetch must not run")
    svc.ollama = MagicMock()
    svc.ollama.chat.return_value = FAKE_QUESTION_JSON

    q = svc.generate_single_question(
        source="ignored://",
        model="dummy",
        source_info_override=_make_override(),
    )

    svc.content.fetch.assert_not_called()
    assert q is not None
    assert q["question"] == "問題?"


def test_single_question_without_override_still_calls_fetch():
    svc = QuizService()
    svc.content = MagicMock()
    svc.content.fetch.return_value = {
        "title": "Live", "content": "live content", "source": "https://live",
        "type": "url_deep", "depth": 1, "doc_types": ["table"],
        "page_count": 1, "pages": [], "document_id": 99,
    }
    svc.ollama = MagicMock()
    svc.ollama.chat.return_value = FAKE_QUESTION_JSON

    svc.generate_single_question(source="https://live", model="x")
    svc.content.fetch.assert_called_once()


# ------------------------------------------------------------------
# Route-level smoke: /api/quiz/regenerate-question with session_id
# ------------------------------------------------------------------
def test_regenerate_endpoint_uses_stored_document(monkeypatch):
    """Integration-ish: the route looks up documents by session_id
    and forwards the override to the service."""
    import app as app_module

    called_with_override = {"flag": False, "source_info": None}

    def fake_single(**kwargs):
        called_with_override["flag"] = kwargs.get("source_info_override") is not None
        called_with_override["source_info"] = kwargs.get("source_info_override")
        return {
            "id": "Q001", "level": "K2", "topic": "t", "question": "?",
            "diagram": "", "choices": {"a":"","b":"","c":"","d":""},
            "answer": "a", "explanation": "e", "source_hint": "",
        }

    monkeypatch.setattr(
        app_module.app_module if hasattr(app_module, "app_module") else app_module,
        "__name__", "app",  # noop — just to keep importlib happy
    )
    # Patch the service method on the live blueprint instance.
    from app.api import quiz as quiz_module
    monkeypatch.setattr(
        quiz_module._quiz_service, "generate_single_question", fake_single,
    )
    # Stub the document loader so we don't need a real SQLite row.
    monkeypatch.setattr(
        quiz_module, "_load_existing_session",
        lambda sid: {"questions": [], "topics": [], "document_id": 77},
    )
    monkeypatch.setattr(
        quiz_module, "_load_document_as_source_info",
        lambda did: _make_override(),
    )

    client = app_module.app.test_client()
    r = client.post("/api/quiz/regenerate-question", json={
        "source": "https://anything",  # ignored in favor of stored
        "model": "dummy",
        "session_id": "sess-xyz",
        "question_id": "Q001",
    })
    assert r.status_code == 200, r.get_json()
    assert called_with_override["flag"] is True
    assert called_with_override["source_info"]["document_id"] == 42


def test_append_mode_offsets_qnum_past_existing(monkeypatch):
    """Append mode must number new questions starting AFTER existing ones so
    the frontend's userAnswers[id] map doesn't accidentally bleed saved
    answers into fresh questions that reused Q001/Q002/... ids."""
    from app.api import quiz as quiz_module
    import app as app_module

    existing_questions = [
        {"id": f"Q{i:03d}", "level": "K2", "topic": f"t{i}", "question": f"q{i}"}
        for i in range(1, 11)
    ]
    captured = {"qnum_start": None, "exclude_q_texts": None}

    def fake_incremental(**kwargs):
        captured["qnum_start"] = kwargs.get("qnum_start")
        captured["exclude_q_texts"] = kwargs.get("exclude_question_texts")
        # Emit the minimum viable SSE trace so the route completes.
        yield ("source_info", {"session_id": kwargs.get("session_id"),
                                "title": "t", "source": "s", "type": "x",
                                "depth": 1, "doc_types": [], "page_count": 1})
        yield ("done", {
            "session_id": kwargs.get("session_id"),
            "generated_at": "2026-04-15T00:00:00Z",
            "model": kwargs.get("model"),
            "question_count": 0, "questions": [],
            "source_info": {},
        })

    monkeypatch.setattr(
        quiz_module._quiz_service, "generate_incremental", fake_incremental,
    )
    monkeypatch.setattr(
        quiz_module, "_load_existing_session",
        lambda sid: {
            "questions": existing_questions,
            "topics": [f"{q['topic']} ({q['level']})" for q in existing_questions],
            "document_id": None,
        },
    )

    client = app_module.app.test_client()
    r = client.post("/api/quiz/generate", json={
        "source": "https://example.com",
        "model": "dummy",
        "count": 5,
        "append_to_session_id": "sess-123",
    })
    # SSE 200 even with all-empty body.
    assert r.status_code == 200
    # The key fix: qnum_start == 11 when 10 existing questions are loaded.
    assert captured["qnum_start"] == 11, (
        f"expected qnum_start=11, got {captured['qnum_start']}"
    )
    assert captured["exclude_q_texts"] is not None
    assert len(captured["exclude_q_texts"]) == 10
    assert captured["exclude_q_texts"][0] == "q1"


def test_regenerate_endpoint_without_session_falls_back(monkeypatch):
    """No session_id => no override, service receives None."""
    from app.api import quiz as quiz_module
    import app as app_module

    called = {"override": "unset"}

    def fake_single(**kwargs):
        called["override"] = kwargs.get("source_info_override")
        return {
            "id": "Q001", "level": "K2", "topic": "t", "question": "?",
            "diagram": "", "choices": {"a":"","b":"","c":"","d":""},
            "answer": "a", "explanation": "e", "source_hint": "",
        }
    monkeypatch.setattr(
        quiz_module._quiz_service, "generate_single_question", fake_single,
    )

    client = app_module.app.test_client()
    r = client.post("/api/quiz/regenerate-question", json={
        "source": "https://live",
        "model": "dummy",
        # no session_id
    })
    assert r.status_code == 200
    assert called["override"] is None
