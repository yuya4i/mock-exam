"""Tests for the PERF-B helpers in quiz_service.

- ``_compute_num_ctx``: chooses an Ollama num_ctx tier based on the
  content character count, clamped to NUM_CTX_MIN/NUM_CTX_MAX.
- ``QuizService._resolve_model``: fallback chain + permissive
  return-as-is when the model list is unknown / mock'd.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.quiz_service import (
    QuizService,
    _compute_num_ctx,
    NUM_CTX_MAX,
    NUM_CTX_MIN,
)


@pytest.mark.parametrize("chars, expected_min, expected_max", [
    (0,      NUM_CTX_MIN, NUM_CTX_MIN),
    (500,    NUM_CTX_MIN, 4096),
    (3000,   NUM_CTX_MIN, 4096),
    (8000,   4096,        NUM_CTX_MAX),
    (12000,  6144,        NUM_CTX_MAX),
    (50_000, 8192,        NUM_CTX_MAX),
])
def test_compute_num_ctx_tiers(chars, expected_min, expected_max):
    out = _compute_num_ctx(chars)
    assert NUM_CTX_MIN <= out <= NUM_CTX_MAX
    assert expected_min <= out <= expected_max


def test_resolve_model_returns_requested_when_installed():
    svc = QuizService()
    svc.ollama = MagicMock()
    svc.ollama.list_models.return_value = [
        {"name": "qwen2.5:7b"}, {"name": "llama3:8b"},
    ]
    assert svc._resolve_model("qwen2.5:7b") == "qwen2.5:7b"


def test_resolve_model_uses_fallback_when_requested_missing(monkeypatch):
    monkeypatch.setattr(
        "app.services.quiz_service.FALLBACK_MODELS",
        ["fallback:8b", "fallback:13b"],
    )
    svc = QuizService()
    svc.ollama = MagicMock()
    svc.ollama.list_models.return_value = [
        {"name": "fallback:13b"}, {"name": "other:7b"},
    ]
    assert svc._resolve_model("not-installed:99b") == "fallback:13b"


def test_resolve_model_returns_requested_when_list_models_breaks():
    """When list_models raises a non-ConnectionError (e.g. a Mock that
    doesn't return a list), we trust the caller and forward the
    requested name. Otherwise tests that mock self.ollama would have
    to also mock list_models."""
    svc = QuizService()
    svc.ollama = MagicMock()
    svc.ollama.list_models.side_effect = RuntimeError("boom")
    assert svc._resolve_model("anything:tag") == "anything:tag"


def test_resolve_model_propagates_connection_error():
    """ConnectionError from list_models means Ollama itself is down.
    Don't swallow — the API layer maps it to 503."""
    svc = QuizService()
    svc.ollama = MagicMock()
    svc.ollama.list_models.side_effect = ConnectionError("ollama down")
    with pytest.raises(ConnectionError):
        svc._resolve_model("any-model")


def test_resolve_model_returns_requested_when_no_fallback_match(monkeypatch):
    """No fallback installed → still return requested (let Ollama
    auto-pull or surface its own error — better message than ours)."""
    monkeypatch.setattr(
        "app.services.quiz_service.FALLBACK_MODELS",
        ["fallback:8b"],  # not installed
    )
    svc = QuizService()
    svc.ollama = MagicMock()
    svc.ollama.list_models.return_value = [{"name": "other:7b"}]
    assert svc._resolve_model("not-installed:99b") == "not-installed:99b"
