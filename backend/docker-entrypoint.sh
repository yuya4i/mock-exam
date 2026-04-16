#!/bin/sh
# ============================================================
# QuizGen backend entrypoint (production / non-root mode)
# ============================================================
# Self-heals one specific failure mode that bites every operator who
# upgrades from a root-only build to a non-root image while keeping
# their persisted SQLite volume:
#
#     sqlite3.OperationalError: attempt to write a readonly database
#
# The volume's files are still root-owned from the previous deploy, but
# the new container runs as appuser (UID 1000). chown them once at
# startup, then drop privileges via gosu and exec the real CMD.
#
# Idempotent: chown is a no-op when files are already appuser-owned, so
# running it on every container start is safe and cheap (~1 ms for a
# few-MB SQLite file).
#
# Why a shell entrypoint and not a Python wrapper:
#   - Avoids a second Python process / signal-handling layer.
#   - `exec gosu` replaces the shell so PID 1 is Flask, signals work,
#     and there's nothing to collect on shutdown.
# ============================================================
set -e

CACHE_DIR="${CACHE_DIR:-/app/.cache}"

# Only attempt the chown when the directory exists *and* we are root.
# In tests / non-Docker contexts this script could conceivably be
# invoked as a regular user; in that case the chown would just fail.
if [ "$(id -u)" = "0" ] && [ -d "$CACHE_DIR" ]; then
    chown -R appuser:appuser "$CACHE_DIR" 2>/dev/null || true
fi

# Drop privileges and exec the CMD. gosu replaces the shell so signals
# (SIGTERM / SIGINT) reach Flask directly — important for clean shutdown
# of the SSE generators.
exec gosu appuser "$@"
