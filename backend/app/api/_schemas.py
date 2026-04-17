"""
Pydantic V2 request schemas for /api/* JSON bodies (P1-C).

Why this layer (and not _validation.py for everything)
------------------------------------------------------
``_validation.py`` (P0-2) was deliberately dependency-free so it could
ship with the first hardening pass. P1-C's job is to formalize the
request schemas where the surface is large (POST bodies with many
correlated fields), and Pydantic V2 buys us:

  - declarative schema (one place to read the contract)
  - cross-field validation via ``model_validator``
  - free coercion (str→int, list of literals, etc.)
  - schema introspection that future OpenAPI generation can build on

Query parameters (small, single-value, mostly read on GETs) keep using
``_validation.py`` — Pydantic for those would buy little.

Error contract
--------------
Each schema below raises ``pydantic.ValidationError`` on bad input;
the route handler turns the first error into a Japanese 400 message
via ``humanize_first_error()``. The wire format remains the same as
P0-2: ``{"error": "<message>"}`` with status 400.
"""
from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# Re-exported so route handlers don't need to import from pydantic directly.
__all__ = [
    "ContentRequest",
    "QuizGenerateRequest",
    "RegenerateQuestionRequest",
    "DocumentCreateRequest",
    "AnswersRequest",
    "ValidationError",
    "humanize_first_error",
]

import re

MAX_DEPTH = 8
MAX_DOCUMENT_CONTENT_BYTES = 1 * 1024 * 1024  # match documents.py P0-2 cap

DocType = Literal["table", "csv", "pdf", "png"]
KLevel = Literal["K1", "K2", "K3", "K4"]
Difficulty = Literal["easy", "medium", "hard"]

# SEC-5: session_id is generated server-side as uuid4 (36-char dashed),
# but every API surface that accepts one (request body + URL path)
# previously only checked length. A weird session_id wouldn't reach SQL
# injection (we use parameter binding) but it could end up logged,
# echoed back into URLs, or used in path joins by future code. Pin the
# allowed charset to the actual generated alphabet plus a small bit of
# slack (underscores) for tests / future namespacing.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_session_id(value: str) -> bool:
    return isinstance(value, str) and bool(SESSION_ID_RE.match(value))


# --------------------------------------------------------------------------
# Error humanization
# --------------------------------------------------------------------------
def humanize_first_error(exc: ValidationError) -> str:
    """Map the first pydantic error to a Japanese, user-safe message.

    Pydantic's default messages are English and mention library
    internals; the API contract since P0-2 is "user-friendly Japanese
    on 400". This helper keeps that contract.
    """
    err = exc.errors()[0]
    field = ".".join(str(p) for p in err["loc"]) or "入力"
    typ = err["type"]
    ctx = err.get("ctx", {})
    msg = err.get("msg", "")

    if typ in ("missing", "string_too_short"):
        return f"{field} は必須です。"
    if typ in ("string_too_long",):
        max_len = ctx.get("max_length", "上限")
        return f"{field} は {max_len} 文字以内で指定してください。"
    if typ in ("int_parsing", "int_type", "int_from_float"):
        return f"{field} は整数で指定してください。"
    if typ in ("less_than_equal",):
        return f"{field} は {ctx.get('le', '上限値')} 以下で指定してください。"
    if typ in ("greater_than_equal",):
        return f"{field} は {ctx.get('ge', '下限値')} 以上で指定してください。"
    if typ in ("literal_error",):
        expected = ctx.get("expected", "")
        return f"{field} は次のいずれかで指定してください: {expected}"
    if typ in ("list_type",):
        return f"{field} はリストで指定してください。"
    if typ in ("dict_type",):
        return f"{field} は辞書形式で指定してください。"
    if typ in ("string_type",):
        return f"{field} は文字列で指定してください。"
    if typ.startswith("value_error"):
        # ValueError raised in a custom validator: surface its message
        # which we author in Japanese.
        return f"{field}: {msg}" if field != "入力" else msg
    return f"{field}: {msg}"


# --------------------------------------------------------------------------
# Shared base for content fetching
# --------------------------------------------------------------------------
class _ScrapeMixin(BaseModel):
    """Fields used by every endpoint that triggers a content fetch.

    ``source`` carries either a URL (validated by safe_fetch downstream)
    or plain text (routed to PlainTextPlugin). The schema layer doesn't
    distinguish — that's the ContentService's job.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    source: str = Field(min_length=1, max_length=2048)
    depth: int = Field(default=1, ge=1, le=MAX_DEPTH)
    doc_types: list[DocType] = Field(default_factory=lambda: ["table", "csv", "pdf", "png"])

    @field_validator("doc_types", mode="after")
    @classmethod
    def _doc_types_default_when_empty(cls, v: list[DocType]) -> list[DocType]:
        return v or ["table", "csv", "pdf", "png"]


class ContentRequest(_ScrapeMixin):
    """Body for ``POST /api/content/preview`` and ``/api/content/fetch``."""


class QuizGenerateRequest(_ScrapeMixin):
    """Body for ``POST /api/quiz/generate``."""

    model: str = Field(min_length=1, max_length=256)
    count: int = Field(default=5, ge=1, le=20)
    levels: list[KLevel] = Field(default_factory=lambda: ["K2", "K3", "K4"])
    difficulty: Difficulty = "medium"
    ollama_options: dict = Field(default_factory=dict)

    # Optional: when set, the new questions are APPENDED to the existing
    # session instead of starting a fresh one. The route handler:
    #   - looks up the existing session's questions and seeds the
    #     "previously generated topics" diversity prompt with them,
    #   - reuses the existing session_id (no new uuid),
    #   - merges existing + new in the SSE `done` payload,
    #   - UPDATEs the SQLite row instead of INSERTing a new one.
    # Empty / missing means "fresh generation" (the original behavior).
    append_to_session_id: str | None = Field(default=None, max_length=64)

    @field_validator("levels", mode="after")
    @classmethod
    def _levels_default_when_empty(cls, v: list[KLevel]) -> list[KLevel]:
        return v or ["K2", "K3", "K4"]

    @field_validator("append_to_session_id", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("append_to_session_id", mode="after")
    @classmethod
    def _check_session_id_charset(cls, v):
        if v is not None and not is_valid_session_id(v):
            raise ValueError(
                "append_to_session_id は 1〜64 文字の英数字 / ハイフン / アンダースコアで指定してください。"
            )
        return v


# --------------------------------------------------------------------------
# Single-question regenerate
# --------------------------------------------------------------------------
class RegenerateQuestionRequest(_ScrapeMixin):
    """Body for ``POST /api/quiz/regenerate-question``.

    Used when the frontend detects an unrenderable artifact (currently:
    a Mermaid SyntaxError) and wants to swap that single question for a
    fresh one. The new question must avoid the topics the user has
    already seen — including the failing one — to prevent oscillation.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    model: str = Field(min_length=1, max_length=256)
    level: KLevel = "K2"
    difficulty: Difficulty = "medium"
    ollama_options: dict = Field(default_factory=dict)

    # Topics already in the session (free-form short strings). The
    # diversity prompt seeds these so the regenerated question explores
    # a different theme.
    exclude_topics: list[str] = Field(default_factory=list, max_length=200)

    # Optional: if both are provided, the server replaces the matching
    # question in the SQLite session so the fix is persisted.
    session_id: str | None = Field(default=None, max_length=64)
    question_id: str | None = Field(default=None, max_length=64)

    @field_validator("session_id", "question_id", mode="before")
    @classmethod
    def _blank_to_none_id(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("session_id", mode="after")
    @classmethod
    def _check_session_id_charset(cls, v):
        if v is not None and not is_valid_session_id(v):
            raise ValueError(
                "session_id は 1〜64 文字の英数字 / ハイフン / アンダースコアで指定してください。"
            )
        return v


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
class DocumentCreateRequest(BaseModel):
    """Body for ``POST /api/documents``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title: str = Field(min_length=1, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    content: str = Field(min_length=1)
    source_type: str = Field(min_length=1, max_length=64)
    page_count: int = Field(default=1, ge=1, le=10_000)
    doc_types: list[str] = Field(default_factory=list)

    @field_validator("url", mode="before")
    @classmethod
    def _url_blank_to_none(cls, v):
        # The legacy contract treated empty strings as "no URL".
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @model_validator(mode="after")
    def _content_byte_cap(self) -> "DocumentCreateRequest":
        if len(self.content.encode("utf-8")) > MAX_DOCUMENT_CONTENT_BYTES:
            raise ValueError(
                f"content は {MAX_DOCUMENT_CONTENT_BYTES} バイト以内で指定してください。"
            )
        return self


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
class AnswersRequest(BaseModel):
    """Body for ``POST /api/results/<session_id>/answers``."""

    model_config = ConfigDict(extra="ignore")

    answers: dict[str, str] = Field(min_length=1)
    score_correct: int = Field(default=0, ge=0, le=1_000_000)
    score_total: int = Field(default=0, ge=0, le=1_000_000)
