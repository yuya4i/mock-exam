"""
Pytest bootstrap for the backend.

Redirects DB_PATH and HISTORY_FILE to /tmp so importing ``app`` (which
performs ``init_db()`` and ``HistoryService()`` at module load — see
audit finding M-002) does not try to mkdir ``/app/.cache`` outside the
container. Also wipes the SSRF policy env vars so every test starts from
the strict default.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# These must be set before the first ``import app``.
_tmp = Path(tempfile.gettempdir())
os.environ.setdefault("DB_PATH", str(_tmp / "quiz_test.db"))
os.environ.setdefault("HISTORY_FILE", str(_tmp / "quiz_test_history.json"))

# Wipe SSRF overrides; individual tests opt in by overriding FetchPolicy
# directly rather than mutating os.environ.
for _k in ("ALLOW_HTTP", "ALLOW_PRIVATE_NETWORKS", "MAX_FETCH_BYTES", "MAX_REDIRECTS"):
    os.environ.pop(_k, None)

# Ensure the backend package is on sys.path for `from app...` imports when
# pytest is invoked from the repo root.
_repo_backend = Path(__file__).resolve().parents[1]
if str(_repo_backend) not in sys.path:
    sys.path.insert(0, str(_repo_backend))
