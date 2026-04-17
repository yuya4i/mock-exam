"""Tests for _is_valid_question_shape (SEC-1).

The previous _parse_single_question only checked `isinstance(q, dict)`
and `"question" in q`, so a model that returned just
``{"question": "x"}`` would survive past parsing and become a
dead-end card with no answer buttons. The strict shape check rejects
those so the caller's retry loop can try again.
"""
from __future__ import annotations

from app.services.quiz_service import _is_valid_question_shape


def _ok():
    return {
        "question": "What is 2+2?",
        "choices": {"a": "3", "b": "4", "c": "5", "d": "6"},
        "answer": "b",
    }


def test_valid_minimal_shape():
    assert _is_valid_question_shape(_ok()) is True


def test_missing_question():
    q = _ok(); del q["question"]
    assert _is_valid_question_shape(q) is False


def test_empty_question():
    q = _ok(); q["question"] = "   "
    assert _is_valid_question_shape(q) is False


def test_question_not_string():
    q = _ok(); q["question"] = 42
    assert _is_valid_question_shape(q) is False


def test_missing_choices():
    q = _ok(); del q["choices"]
    assert _is_valid_question_shape(q) is False


def test_choices_not_dict():
    q = _ok(); q["choices"] = ["a", "b", "c", "d"]
    assert _is_valid_question_shape(q) is False


def test_choices_too_few():
    q = _ok(); q["choices"] = {"a": "only one"}
    assert _is_valid_question_shape(q) is False


def test_choice_value_empty():
    q = _ok(); q["choices"] = {"a": "x", "b": "  "}
    assert _is_valid_question_shape(q) is False


def test_choice_value_not_string():
    q = _ok(); q["choices"] = {"a": "x", "b": 42}
    assert _is_valid_question_shape(q) is False


def test_choice_key_empty():
    q = _ok(); q["choices"] = {"": "x", "b": "y"}
    assert _is_valid_question_shape(q) is False


def test_missing_answer():
    q = _ok(); del q["answer"]
    assert _is_valid_question_shape(q) is False


def test_answer_not_in_choices():
    q = _ok(); q["answer"] = "z"
    assert _is_valid_question_shape(q) is False


def test_answer_case_insensitive_match():
    q = _ok(); q["answer"] = "B"
    assert _is_valid_question_shape(q) is True


def test_input_not_dict():
    assert _is_valid_question_shape("not a dict") is False
    assert _is_valid_question_shape([1, 2, 3]) is False
    assert _is_valid_question_shape(None) is False


def test_extra_fields_are_fine():
    q = _ok()
    q["explanation"] = "long explanation"
    q["topic"] = "Math"
    q["level"] = "K2"
    q["diagram"] = "flowchart LR\n  A --> B"
    q["source_hint"] = "page 1"
    q["bonus_field"] = {"unrelated": True}
    assert _is_valid_question_shape(q) is True
