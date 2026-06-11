#!/usr/bin/env bash
# Re-heal quiz-app host port forwarding after a Windows sleep/resume.
#
# Docker Desktop on WSL2 intermittently drops the host->container port
# proxy when the machine resumes from sleep: the containers stay
# "healthy" (internal :4321 answers) but the host's localhost:4321 /
# :1234 become unreachable until the stack is restarted. This script is
# the idempotent heal — fired by a Windows Task Scheduler task on the
# "system resumed" power event (Microsoft-Windows-Power-Troubleshooter,
# EventID 1). See docs/operations/remote-gpu.md.
#
# Idempotent: if the host can already reach the backend it does nothing.
set -u

cd "$(dirname "$0")/.." || exit 0
COMPOSE="docker compose -f docker-compose.yml"
LOG="${HOME}/.cache/quizgpu-resume-heal.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"; }

log "=== resume-heal start ==="

# Wait for the docker daemon to be responsive after resume (up to ~60s).
for _ in $(seq 1 30); do
  docker info >/dev/null 2>&1 && break
  sleep 2
done
if ! docker info >/dev/null 2>&1; then
  log "docker daemon not responsive after 60s — giving up"
  exit 0
fi

probe() {
  curl -s -m 5 -o /dev/null -w "%{http_code}" \
    http://localhost:4321/api/health 2>/dev/null || echo 000
}

code="$(probe)"
if [ "$code" = "200" ]; then
  log "backend reachable ($code) — no action"
  exit 0
fi

log "backend unreachable ($code) — restarting stack"
$COMPOSE restart >>"$LOG" 2>&1
sleep 4
code2="$(probe)"
log "post-restart backend = $code2"
exit 0
