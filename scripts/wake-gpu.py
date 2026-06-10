#!/usr/bin/env python3
"""Wake-on-LAN sender for the GPU host (no external deps).

Why this exists
---------------
The quiz-app runtime (Flask + Ollama) lives on the GPU PC, which sleeps
when idle to save power. The always-on node (pi-calc) — or any machine
on the same LAN — sends a Wake-on-LAN "magic packet" to bring the GPU
PC up before a generation session, then the user hits the app as usual.

This is intentionally dependency-free (pure ``socket``) so it runs on a
bare Raspberry Pi / Debian without ``apt install wakeonlan``.

Usage
-----
    python3 wake-gpu.py <MAC> [--broadcast 192.168.10.255] [--port 9]
    python3 wake-gpu.py 2C-FD-A1-DE-74-DD
    python3 wake-gpu.py 2C-FD-A1-DE-74-DD --broadcast 192.168.10.255

MAC accepts ``-``, ``:`` or no separators. The magic packet is sent to
the broadcast address (default 255.255.255.255) on UDP port 9 (and 7 as
a fallback, since some NICs listen on the legacy echo port).

Environment fallbacks (so a systemd unit / cron can stay arg-free):
    GPU_MAC        — target MAC if not given as the first CLI arg
    GPU_BROADCAST  — broadcast address (default 255.255.255.255)

Exit codes: 0 sent, 2 bad MAC / missing target.

NOTE: this only SENDS the packet. The GPU PC must be configured to be
woken by it — see docs/operations/remote-gpu.md (BIOS WoL, Windows NIC
"Wake on Magic Packet", Fast Startup off) — otherwise the packet is a
no-op.
"""
from __future__ import annotations

import argparse
import os
import sys

# Share the magic-packet core with wol_server.py (sibling module).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wol import send_wol  # noqa: E402

# Backwards-compatible aliases (older callers / tests referenced these).
from wol import normalize_mac as _normalize_mac  # noqa: E402,F401
from wol import build_magic_packet as _build_magic_packet  # noqa: E402,F401


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Send a Wake-on-LAN magic packet.")
    parser.add_argument(
        "mac", nargs="?", default=os.getenv("GPU_MAC"),
        help="target MAC (XX-XX-XX-XX-XX-XX). Falls back to $GPU_MAC.",
    )
    parser.add_argument(
        "--broadcast", default=os.getenv("GPU_BROADCAST", "255.255.255.255"),
        help="broadcast address (default 255.255.255.255 or $GPU_BROADCAST). "
             "Prefer the subnet broadcast, e.g. 192.168.10.255.",
    )
    parser.add_argument("--port", type=int, default=9, help="UDP port (default 9)")
    args = parser.parse_args(argv)

    if not args.mac:
        parser.error("MAC を指定してください (引数 or $GPU_MAC)")

    try:
        send_wol(args.mac, args.broadcast, args.port)
    except ValueError as e:
        print(f"[wake-gpu] {e}", file=sys.stderr)
        return 2

    print(
        f"[wake-gpu] magic packet 送信: mac={args.mac} "
        f"broadcast={args.broadcast} port={args.port}/7"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
