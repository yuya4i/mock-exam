"""
Minimal, dependency-free request-validation helpers.

Purpose:
    Replace the bare ``int(request.args.get(...))`` / ``int(body.get(...))``
    calls scattered across the API blueprints. Those raised uncaught
    ``ValueError`` / ``TypeError`` for any non-numeric user input and became
    500-class responses. This module makes every parse return a predictable
    ``(value, error)`` tuple so callers can emit a 400 with a user-safe
    message.

    The layer is intentionally simple. It does NOT replace Pydantic — a full
    schema layer is planned for Phase 1 of the hardening roadmap. Here we
    only cover the primitives that actually show up in the request path
    today (integers, string allowlists, comma-separated enum lists).

Usage:
    >>> depth, err = parse_int(body.get("depth"), "depth", default=1, min_val=1, max_val=8)
    >>> if err:
    ...     return jsonify({"error": err}), 400
"""
from __future__ import annotations

from typing import Iterable


def parse_int(
    raw,
    name: str,
    *,
    default: int | None = None,
    min_val: int | None = None,
    max_val: int | None = None,
) -> tuple[int | None, str | None]:
    """Parse ``raw`` as an integer.

    Args:
        raw: The incoming value. Accepts ``int``, ``str``, or ``None``.
            ``None`` and ``""`` fall back to ``default``.
        name: Parameter name used in the error message.
        default: Returned when ``raw`` is missing. ``None`` means "required".
        min_val: Inclusive lower bound. ``None`` disables the check.
        max_val: Inclusive upper bound. ``None`` disables the check.

    Returns:
        ``(value, None)`` on success, or ``(None, error_message)`` on
        validation failure. The error message is safe to return to the
        client and is localized in Japanese to match the existing API.
    """
    if raw is None or raw == "":
        if default is None:
            return None, f"{name} は必須です。"
        return default, None

    if isinstance(raw, bool):
        # Booleans are a subclass of int in Python; reject explicitly so
        # ``True`` / ``False`` don't silently become 1 / 0.
        return None, f"{name} は整数で指定してください。"

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"{name} は整数で指定してください。"

    if min_val is not None and value < min_val:
        return None, f"{name} は {min_val} 以上で指定してください。"
    if max_val is not None and value > max_val:
        return None, f"{name} は {max_val} 以下で指定してください。"
    return value, None


def parse_str_enum(
    raw,
    name: str,
    allowed: Iterable[str],
    *,
    default: str | None = None,
    lower: bool = False,
) -> tuple[str | None, str | None]:
    """Parse ``raw`` as a string restricted to an allowlist.

    Args:
        raw: Incoming value.
        name: Parameter name for the error message.
        allowed: Permitted values.
        default: Returned when ``raw`` is missing. ``None`` means "required".
        lower: If True, lowercases ``raw`` before the comparison.

    Returns:
        ``(value, None)`` on success, ``(None, error_message)`` on failure.
    """
    allowed_set = set(allowed)
    if raw is None or raw == "":
        if default is None:
            return None, f"{name} は必須です。"
        return default, None

    if not isinstance(raw, str):
        return None, f"{name} は文字列で指定してください。"

    value = raw.strip()
    if lower:
        value = value.lower()

    if value not in allowed_set:
        allowed_display = ", ".join(sorted(allowed_set))
        return None, f"{name} は次のいずれかで指定してください: {allowed_display}"
    return value, None


def parse_str_list(
    raw,
    name: str,
    *,
    allowed: Iterable[str] | None = None,
    default: list[str] | None = None,
    allow_empty: bool = False,
    separator: str = ",",
) -> tuple[list[str] | None, str | None]:
    """Parse ``raw`` as a list of strings.

    Accepts either a Python list (from JSON body) or a string that will be
    split on ``separator`` (from a query parameter). Empty strings are
    filtered out. If ``allowed`` is provided, the list is intersected with
    it.

    Args:
        raw: Incoming value (``list`` or ``str``).
        name: Parameter name for the error message.
        allowed: Optional allowlist; filters the result set.
        default: Returned when ``raw`` is missing.
        allow_empty: If False, an empty result after filtering is an error.
        separator: Separator used when ``raw`` is a string.

    Returns:
        ``(value, None)`` on success, ``(None, error_message)`` on failure.
    """
    if raw is None or raw == "":
        if default is None:
            if allow_empty:
                return [], None
            return None, f"{name} は必須です。"
        return list(default), None

    if isinstance(raw, str):
        items = [p.strip() for p in raw.split(separator) if p.strip()]
    elif isinstance(raw, list):
        items = []
        for item in raw:
            if not isinstance(item, str):
                return None, f"{name} の要素は文字列で指定してください。"
            s = item.strip()
            if s:
                items.append(s)
    else:
        return None, f"{name} はリスト形式で指定してください。"

    if allowed is not None:
        allowed_set = set(allowed)
        items = [i for i in items if i in allowed_set]

    if not items and not allow_empty:
        if default is not None:
            return list(default), None
        return None, f"{name} を 1 件以上指定してください。"

    return items, None


def parse_non_empty_str(
    raw,
    name: str,
    *,
    max_len: int | None = None,
) -> tuple[str | None, str | None]:
    """Parse ``raw`` as a required non-empty string.

    Trims whitespace. Rejects non-string types and blank-after-trim values.
    Optionally enforces a maximum length.
    """
    if raw is None:
        return None, f"{name} は必須です。"
    if not isinstance(raw, str):
        return None, f"{name} は文字列で指定してください。"
    value = raw.strip()
    if not value:
        return None, f"{name} は必須です。"
    if max_len is not None and len(value) > max_len:
        return None, f"{name} は {max_len} 文字以内で指定してください。"
    return value, None
