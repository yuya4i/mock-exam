"""
Tests for the Pydantic V2 request schemas (P1-C).

Schemas are tested in isolation here. The endpoint-level integration
tests in test_security.py / the manual Flask test-client smoke runs
verify that humanize_first_error() messages reach the wire.
"""
from __future__ import annotations

import pytest

from app.api._schemas import (
    AnswersRequest,
    ContentRequest,
    DocumentCreateRequest,
    QuizGenerateRequest,
    ValidationError,
    humanize_first_error,
)


# ------------------------------------------------------------------
# ContentRequest
# ------------------------------------------------------------------
def test_content_default_doc_types_when_omitted():
    req = ContentRequest.model_validate({"source": "hi"})
    assert req.depth == 1
    assert req.doc_types == ["table", "csv", "pdf", "png"]


def test_content_strips_whitespace_on_source():
    req = ContentRequest.model_validate({"source": "  hi  "})
    assert req.source == "hi"


def test_content_doc_types_empty_falls_back_to_default():
    req = ContentRequest.model_validate({"source": "x", "doc_types": []})
    assert req.doc_types == ["table", "csv", "pdf", "png"]


@pytest.mark.parametrize(
    "body,expected_part",
    [
        ({}, "source"),
        ({"source": ""}, "source"),
        ({"source": "x", "depth": "abc"}, "depth"),
        ({"source": "x", "depth": 0}, "depth"),
        ({"source": "x", "depth": 9}, "depth"),
        ({"source": "x", "doc_types": ["bogus"]}, "doc_types"),
    ],
)
def test_content_invalid_inputs(body, expected_part):
    with pytest.raises(ValidationError) as exc:
        ContentRequest.model_validate(body)
    assert expected_part in humanize_first_error(exc.value)


# ------------------------------------------------------------------
# QuizGenerateRequest
# ------------------------------------------------------------------
def test_quiz_defaults():
    req = QuizGenerateRequest.model_validate({"source": "x", "model": "qwen2.5"})
    assert req.count == 5
    assert req.difficulty == "medium"
    assert req.levels == ["K2", "K3", "K4"]
    assert req.ollama_options == {}
    assert req.append_to_session_id is None


def test_quiz_append_to_session_accepts_string():
    req = QuizGenerateRequest.model_validate({
        "source": "x", "model": "qwen2.5",
        "append_to_session_id": "sess-abc-123",
    })
    assert req.append_to_session_id == "sess-abc-123"


def test_quiz_append_to_session_blank_becomes_none():
    """The frontend may send "" when no append target is selected;
    treat empty string as "no append" for ergonomic reasons."""
    req = QuizGenerateRequest.model_validate({
        "source": "x", "model": "qwen2.5",
        "append_to_session_id": "",
    })
    assert req.append_to_session_id is None


def test_quiz_append_to_session_max_len():
    """Bounded so an attacker can't shove an unbounded blob into the
    SQL parameter."""
    with pytest.raises(ValidationError):
        QuizGenerateRequest.model_validate({
            "source": "x", "model": "qwen2.5",
            "append_to_session_id": "x" * 65,
        })


@pytest.mark.parametrize(
    "body,expected_part",
    [
        ({}, "source"),
        ({"source": "x"}, "model"),
        ({"source": "x", "model": "y", "count": "abc"}, "count"),
        ({"source": "x", "model": "y", "count": 100}, "count"),
        ({"source": "x", "model": "y", "difficulty": "XX"}, "difficulty"),
        ({"source": "x", "model": "y", "ollama_options": "not-a-dict"}, "ollama_options"),
    ],
)
def test_quiz_invalid_inputs(body, expected_part):
    with pytest.raises(ValidationError) as exc:
        QuizGenerateRequest.model_validate(body)
    assert expected_part in humanize_first_error(exc.value)


# ------------------------------------------------------------------
# DocumentCreateRequest
# ------------------------------------------------------------------
def test_document_url_blank_becomes_none():
    req = DocumentCreateRequest.model_validate(
        {"title": "t", "content": "c", "source_type": "s", "url": ""},
    )
    assert req.url is None


def test_document_content_byte_cap():
    huge = "X" * (1024 * 1024 + 1)
    with pytest.raises(ValidationError) as exc:
        DocumentCreateRequest.model_validate(
            {"title": "t", "content": huge, "source_type": "s"},
        )
    assert "バイト" in humanize_first_error(exc.value)


# ------------------------------------------------------------------
# AnswersRequest
# ------------------------------------------------------------------
def test_answers_empty_dict_is_invalid():
    with pytest.raises(ValidationError) as exc:
        AnswersRequest.model_validate({"answers": {}})
    assert "answers" in humanize_first_error(exc.value)


def test_answers_non_negative_scores():
    with pytest.raises(ValidationError) as exc:
        AnswersRequest.model_validate({"answers": {"q1": "a"}, "score_total": -1})
    assert "score_total" in humanize_first_error(exc.value)


def test_answers_defaults_zero_scores():
    req = AnswersRequest.model_validate({"answers": {"q1": "a"}})
    assert req.score_correct == 0
    assert req.score_total == 0
