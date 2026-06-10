"""Wake-on-LAN core (no external deps).

Single source of truth for the magic-packet logic, shared by the CLI
sender (``wake-gpu.py``) and the web trigger (``wol_server.py``).
"""
from __future__ import annotations

import re
import socket


def normalize_mac(raw: str) -> bytes:
    """Parse a MAC in XX-XX / XX:XX / XXXXXXXXXXXX form into 6 bytes."""
    hexstr = re.sub(r"[^0-9A-Fa-f]", "", raw or "")
    if len(hexstr) != 12:
        raise ValueError(
            f"MAC アドレスが不正です: {raw!r} (16進12桁が必要、解釈後={hexstr!r})"
        )
    return bytes.fromhex(hexstr)


def build_magic_packet(mac_bytes: bytes) -> bytes:
    """6 bytes of 0xFF followed by the target MAC repeated 16 times."""
    return b"\xff" * 6 + mac_bytes * 16


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a WoL magic packet to ``broadcast`` on UDP ``port`` (and 7)."""
    packet = build_magic_packet(normalize_mac(mac))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for p in {port, 7}:  # primary + legacy echo port
            s.sendto(packet, (broadcast, p))
