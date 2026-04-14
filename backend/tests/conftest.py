"""
Pytest bootstrap for the backend.

Since P1-D, the application's data-path defaults are environment-aware
(see app/paths.py) so a bare ``import app`` no longer crashes when
``/app`` is missing — it falls back to ``<tmp>/quizgen/``. This file
therefore needs to do almost nothing on the env side; it only:

  1. Wipes SSRF / auth env vars so every test starts from the strict
     default. Individual tests opt-in via FetchPolicy(...) or
     monkeypatch.setenv("API_TOKEN", ...) when they need a non-default.
  2. Adds backend/ to sys.path so ``from app...`` works regardless of
     where pytest is invoked from.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

for _k in (
    "ALLOW_HTTP",
    "ALLOW_PRIVATE_NETWORKS",
    "MAX_FETCH_BYTES",
    "MAX_REDIRECTS",
    "API_TOKEN",
):
    os.environ.pop(_k, None)

_repo_backend = Path(__file__).resolve().parents[1]
if str(_repo_backend) not in sys.path:
    sys.path.insert(0, str(_repo_backend))
