"""
Environment-aware default paths for runtime data files.

The previous defaults were hard-coded to ``/app/.cache/...`` which is
correct inside the Docker image but fails on every other environment
(local pytest, ad-hoc scripts, IDE indexers) because ``/app`` doesn't
exist there. ``init_db()`` and ``HistoryService.__init__()`` then
crashed at import time with ``PermissionError: '/app'`` (audit M-002).

This module centralizes the resolution so a single rule applies:

  1. If the explicit env var (``DB_PATH`` / ``HISTORY_FILE``) is set,
     honour it verbatim. Operators always win.
  2. Otherwise, if ``/app/.cache`` is usable (we're inside the
     container), use the historical path so existing volumes keep
     working without migration.
  3. Otherwise, fall back to ``<tempfile.gettempdir()>/quizgen/<name>``,
     which is writable by the current user on every supported OS.

The fallback choice is logged once per process so operators notice
when they accidentally end up running outside the container.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

CONTAINER_DATA_DIR = Path("/app/.cache")
FALLBACK_DATA_DIR = Path(tempfile.gettempdir()) / "quizgen"

_FALLBACK_LOGGED = False


def _container_dir_is_usable() -> bool:
    """Return True iff /app/.cache is writable (or createable under /app)."""
    if CONTAINER_DATA_DIR.is_dir() and os.access(CONTAINER_DATA_DIR, os.W_OK):
        return True
    parent = CONTAINER_DATA_DIR.parent
    if parent.is_dir() and os.access(parent, os.W_OK):
        return True
    return False


def resolve_data_path(env_var: str, filename: str) -> str:
    """Return the resolved absolute path for a runtime data file.

    Args:
        env_var: Name of the env var that, if set, wins unconditionally
            (e.g. ``"DB_PATH"`` or ``"HISTORY_FILE"``).
        filename: Default basename used when neither the env var nor the
            container default applies.
    """
    explicit = os.getenv(env_var)
    if explicit:
        return explicit

    if _container_dir_is_usable():
        return str(CONTAINER_DATA_DIR / filename)

    global _FALLBACK_LOGGED
    if not _FALLBACK_LOGGED:
        logger.warning(
            "/app/.cache が利用不可のため、データファイルを %s 配下に作成します。"
            " 本番環境では DB_PATH / HISTORY_FILE を明示するか、コンテナで起動してください。",
            FALLBACK_DATA_DIR,
        )
        _FALLBACK_LOGGED = True
    return str(FALLBACK_DATA_DIR / filename)
