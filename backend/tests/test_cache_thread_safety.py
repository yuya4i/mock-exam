"""Smoke test for the threading.Lock-guarded TTLCache (BACKEND-8).

Hammer the helper from many threads at once. The pre-fix path
(naked `cache_key in _cache; _cache[k]; _cache[k] = v`) periodically
raises RuntimeError when TTLCache's internal expire-purge runs
concurrently with mutation. The lock-guarded helpers must survive
the same load with no exception.
"""
from __future__ import annotations

import threading

from app.services.content_service import _cache_get, _cache_set, _cache


def test_concurrent_cache_get_set_does_not_raise():
    _cache.clear()

    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker(idx: int):
        try:
            barrier.wait(timeout=5)
            for j in range(200):
                key = f"k{(idx * 1000 + j) % 30}"
                _cache_set(key, {"value": j})
                _cache_get(key)
                _cache_get(f"missing-{j}")  # exercise miss path
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, errors
    # Cache should have at least one valid entry left after the storm
    assert len(_cache) > 0


def test_cache_get_returns_none_on_miss():
    _cache.clear()
    assert _cache_get("never-set") is None


def test_cache_set_then_get_round_trip():
    _cache.clear()
    _cache_set("k", {"hi": 1})
    assert _cache_get("k") == {"hi": 1}
