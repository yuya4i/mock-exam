"""Tests for the thread-local DNS pin used to close the SSRF
TOCTOU window between check_url's resolution and the actual TCP
connect (BACKEND-9).
"""
from __future__ import annotations

import socket
import threading

import pytest

from app.services import safe_fetch as sf


def test_pin_overrides_only_inside_context():
    """Outside the context, getaddrinfo behaves normally; inside,
    the pinned hostname returns only the pinned IPs."""
    # Outside: real lookup for localhost should work
    real = socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)
    assert real, "localhost should always resolve"

    with sf.pin_dns("not-a-real-host.invalid", ["1.2.3.4"]):
        out = socket.getaddrinfo(
            "not-a-real-host.invalid", 443, type=socket.SOCK_STREAM,
        )
        addrs = [r[4][0] for r in out]
        assert addrs == ["1.2.3.4"]
        # Other hostnames still pass through to the original resolver
        passthrough = socket.getaddrinfo("localhost", 80, type=socket.SOCK_STREAM)
        assert passthrough  # didn't break

    # After context exits, the pinned hostname falls back to the real
    # resolver — which will fail for an .invalid TLD as it should.
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo(
            "not-a-real-host.invalid", 443, type=socket.SOCK_STREAM,
        )


def test_pin_supports_ipv6():
    with sf.pin_dns("test.invalid", ["::1"]):
        out = socket.getaddrinfo("test.invalid", 443, type=socket.SOCK_STREAM)
        families = [r[0] for r in out]
        addrs = [r[4][0] for r in out]
        assert socket.AF_INET6 in families
        assert "::1" in addrs


def test_pin_supports_multiple_ips_for_one_host():
    with sf.pin_dns("multi.invalid", ["1.2.3.4", "5.6.7.8", "::1"]):
        out = socket.getaddrinfo("multi.invalid", 80, type=socket.SOCK_STREAM)
        addrs = sorted({r[4][0] for r in out})
        assert addrs == sorted(["1.2.3.4", "5.6.7.8", "::1"])


def test_pin_is_thread_local():
    """Two threads pinning the same hostname to different IPs must
    not see each other's overrides."""
    results: dict[str, list[str]] = {}
    barrier = threading.Barrier(2)

    def worker(label: str, ip: str):
        with sf.pin_dns("threadtest.invalid", [ip]):
            barrier.wait(timeout=5)
            out = socket.getaddrinfo(
                "threadtest.invalid", 443, type=socket.SOCK_STREAM,
            )
            results[label] = [r[4][0] for r in out]

    t1 = threading.Thread(target=worker, args=("A", "10.0.0.1"))
    t2 = threading.Thread(target=worker, args=("B", "10.0.0.2"))
    t1.start(); t2.start()
    t1.join(timeout=5); t2.join(timeout=5)

    assert results["A"] == ["10.0.0.1"], results
    assert results["B"] == ["10.0.0.2"], results


def test_nested_pin_restores_outer():
    with sf.pin_dns("nest.invalid", ["1.1.1.1"]):
        with sf.pin_dns("nest.invalid", ["2.2.2.2"]):
            inner = socket.getaddrinfo("nest.invalid", 80, type=socket.SOCK_STREAM)
            assert inner[0][4][0] == "2.2.2.2"
        outer = socket.getaddrinfo("nest.invalid", 80, type=socket.SOCK_STREAM)
        assert outer[0][4][0] == "1.1.1.1"
