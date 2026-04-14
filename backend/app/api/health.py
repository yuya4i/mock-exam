import os
import sys
from flask import Blueprint, jsonify
from app.services.ollama_service import OllamaService

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    ollama = OllamaService()
    ollama_ok = ollama.health()
    return jsonify({
        "status":       "ok",
        "ollama":       "connected" if ollama_ok else "disconnected",
        "ollama_url":   ollama.base_url,
    }), 200


def _read_meminfo_gb():
    """Read MemTotal and MemAvailable from /proc/meminfo (Linux only).

    Returns (ram_total_gb, ram_available_gb) as floats, or (None, None) on failure.
    """
    try:
        total_kb = None
        avail_kb = None
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                # Lines look like: "MemTotal:       16309460 kB"
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                if total_kb is not None and avail_kb is not None:
                    break
        if total_kb is None or avail_kb is None:
            return None, None
        # kB → GB (MemInfo uses kibibytes, 1 GB = 1024 * 1024 kB here = 1 GiB)
        kb_per_gb = 1024 * 1024
        return round(total_kb / kb_per_gb, 2), round(avail_kb / kb_per_gb, 2)
    except Exception:
        return None, None


def _cpu_count():
    try:
        return os.cpu_count() or 0
    except Exception:
        return 0


@health_bp.get("/system/specs")
def system_specs():
    """Return basic host specs so the frontend can warn about
    undersized/oversized Ollama models relative to available RAM.

    On non-Linux hosts (or when /proc/meminfo is unreadable) the RAM fields
    fall back to null and the frontend simply skips the capability check.
    """
    ram_total_gb, ram_available_gb = _read_meminfo_gb()
    return jsonify({
        "ram_total_gb":     ram_total_gb,
        "ram_available_gb": ram_available_gb,
        "cpu_count":        _cpu_count(),
        "platform":         sys.platform,
    }), 200
