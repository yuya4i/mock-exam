"""Tests for ContentService._save_to_db idempotency / race tolerance
(BACKEND-4 / Red Team P1).

Two parallel scrapes of the same URL hit the SELECT→INSERT path; the
old implementation could lose to the UNIQUE(content_hash) constraint
on the second commit, swallow the IntegrityError, and return None to
the second caller. The downstream effect: that caller's quiz_session
ended up with NULL document_id and lost the cached-content reuse
optimisation for append-mode regen.

The fix uses INSERT OR IGNORE + SELECT-after so both callers get a
valid id even when they collide.
"""
from __future__ import annotations

import importlib
import threading

import pytest


@pytest.fixture
def cs(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "history.json"))
    import app.paths as paths_mod
    importlib.reload(paths_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    import app.services.content_service as cs_mod
    importlib.reload(cs_mod)
    db_mod.init_db()
    return cs_mod


def _payload():
    return {
        "title": "T",
        "source": "https://example.com/x",
        "content": "shared body for race test " * 50,
        "type": "url_deep",
        "page_count": 1,
        "doc_types": [],
    }


def test_two_sequential_saves_same_hash_return_same_id(cs):
    """Sequential idempotency — already worked before the fix, but
    pin it so a future refactor can't regress."""
    a = cs.ContentService._save_to_db(_payload())
    b = cs.ContentService._save_to_db(_payload())
    assert a is not None and b is not None
    assert a == b


def test_concurrent_saves_same_hash_both_get_id(cs):
    """The actual race: 8 threads save the same hash concurrently.
    Pre-fix, some would get None due to swallowed IntegrityError.
    Post-fix, all return the canonical row's id."""
    payload = _payload()
    results: list[int | None] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait(timeout=5)
            results.append(cs.ContentService._save_to_db(dict(payload)))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(results) == 8, results
    assert all(r is not None for r in results), (
        f"BACKEND-4: some saves returned None on race; got {results}"
    )
    # All must converge on a single canonical row
    assert len(set(results)) == 1, (
        f"all 8 saves must agree on id; got {results}"
    )


def test_distinct_hashes_get_distinct_ids(cs):
    p1 = _payload()
    p2 = dict(p1, content="totally different body")
    a = cs.ContentService._save_to_db(p1)
    b = cs.ContentService._save_to_db(p2)
    assert a != b
