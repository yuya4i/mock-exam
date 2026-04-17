"""Tests for QuizService._sanitize_diagram (SEC-2 / Red Team P1).

Even though Mermaid's strict mode (default since v10) won't execute
foreignObject/script/onerror payloads at render time, a paranoid
backend chokepoint also strips them from the source so the v-html
sink in QuestionCard.vue is fed clean data and a future Mermaid
config drift can't expose us.

Also enforces a length cap to prevent a runaway LLM (or a prompt
injection that smuggled a 100K-char diagram) from causing client-side
parsing DoS.
"""
from __future__ import annotations

import pytest

from app.services.quiz_service import QuizService, MAX_DIAGRAM_CHARS


def _sanitize(s):
    return QuizService._sanitize_diagram(s)


def test_strips_script_tag_inside_diagram():
    src = (
        "flowchart LR\n"
        '  A["hello <script>alert(1)</script>"] --> B'
    )
    out = _sanitize(src)
    assert "<script" not in out.lower()
    assert "alert" in out  # text body survives, just no tag


def test_strips_foreignobject_tag():
    src = (
        "flowchart LR\n"
        '  A["<foreignObject><iframe src=javascript:alert(1)></iframe></foreignObject>"]'
    )
    out = _sanitize(src)
    assert "foreignobject" not in out.lower()
    assert "iframe" not in out.lower()


def test_strips_onerror_handler_in_img_tag():
    src = (
        "graph TD\n"
        '  A["<img src=x onerror=alert(1)>"] --> B'
    )
    out = _sanitize(src)
    assert "<img" not in out.lower()
    assert "onerror" not in out.lower()


def test_unmatched_lt_does_not_leave_dangling_tag_open():
    """A bare `<script` (no closing `>`) used to slip past the regex
    `<[^>]+>` because the regex requires a closing `>`. We now also
    strip unmatched-open tags."""
    src = "graph TD\n  A[\"<scripthello world\"] --> B"
    out = _sanitize(src)
    # The dangerous `<script` opener must not survive
    assert "<script" not in out.lower()


def test_invalid_diagram_keyword_returns_empty():
    """Unknown diagram type → empty string (FE then skips render)."""
    assert _sanitize("not-a-diagram-type\n  A --> B") == ""


def test_empty_input_returns_empty():
    assert _sanitize("") == ""
    assert _sanitize("   \n\t") == ""


def test_length_cap_drops_oversized_diagrams():
    """Diagrams above the cap are rejected (return empty) so the FE
    won't ship 100KB of Mermaid source to the parser."""
    huge = "flowchart LR\n" + ("  A --> B\n" * 50_000)
    assert len(huge) > MAX_DIAGRAM_CHARS
    assert _sanitize(huge) == ""


def test_at_cap_is_accepted():
    body = "  A --> B\n"
    header = "flowchart LR\n"
    # exactly at cap (not over)
    pad = "x" * max(0, MAX_DIAGRAM_CHARS - len(header) - len(body) - 5)
    src = header + body + "  C[" + pad + "] --> D"
    src = src[:MAX_DIAGRAM_CHARS]  # ensure not over
    out = _sanitize(src)
    assert out != ""


def test_normal_flowchart_passes_through():
    src = "flowchart LR\n  A[Start] --> B[End]"
    out = _sanitize(src)
    assert out.startswith("flowchart")
    assert "A[Start]" in out
