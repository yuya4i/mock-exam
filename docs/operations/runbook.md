# Operations runbook

Operator-facing playbook for running QuizGen. Pairs with
[`docs/architecture.md`](../architecture.md) and
[`SECURITY.md`](../../SECURITY.md).

Last updated **2026-04-15**.

---

## 1. Quick start (copy-paste)

```bash
# Production-oriented (nginx serves built SPA, Flask without --debug):
docker compose up -d --build

# Development with hot reload (Vite HMR + Flask --reload):
docker compose -f docker-compose.dev.yml up -d --build

# Open in browser:
xdg-open http://localhost:1234   # frontend
curl http://localhost:4321/api/health   # backend probe
```

`Ollama` must already be running on the host (`ollama serve`).
Port mapping summary:

| Container        | Host port | Container port | Bound to     |
|------------------|-----------|----------------|--------------|
| `quiz-frontend`  | 1234      | 1234           | `0.0.0.0`    |
| `quiz-backend`   | 4321      | 4321           | `0.0.0.0`    |
| `ollama` (host)  | 11434     | —              | `0.0.0.0` (operator config) |

---

## 2. Environment variables

| Variable                  | Default                                | Effect                                                 |
|---------------------------|----------------------------------------|--------------------------------------------------------|
| `OLLAMA_BASE_URL`         | `http://host.docker.internal:11434`    | Backend → Ollama URL                                   |
| `FLASK_ENV`               | `production` (default compose) / `development` (dev compose) | Flask env                          |
| `CORS_ORIGINS`            | `http://localhost:1234`                | Comma-separated allowed origins                        |
| `DB_PATH`                 | auto (see `app/paths.py`)              | SQLite file. In container: `/app/.cache/quizgen.db`. Outside: `<tmp>/quizgen/quizgen.db` |
| `API_TOKEN`               | unset (auth disabled)                  | Bearer token required on `/api/*` (except `/api/health`) |
| `ALLOW_HTTP`              | unset (https only)                     | Allow `http://` URLs (SSRF policy weakening)           |
| `ALLOW_PRIVATE_NETWORKS`  | unset (public IPs only)                | Allow RFC1918/loopback/link-local. Cloud metadata still denied |
| `MAX_FETCH_BYTES`         | 10 MiB                                 | Per-response body cap                                  |
| `MAX_REDIRECTS`           | 3                                      | Redirect cap (`0` disables)                            |

Any variable can be overridden via shell env at compose time:

```bash
API_TOKEN=$(openssl rand -hex 32) docker compose up -d
```

---

## 3. Health and readiness checks

```bash
# Liveness — is the backend process responsive?
curl -fsS http://localhost:4321/api/health

# Ollama reachability is reported in the same payload:
curl -s http://localhost:4321/api/health | jq .ollama
# "connected" or "disconnected"

# Models actually installed on the operator's Ollama:
curl -s http://localhost:4321/api/models | jq '.models[].name'

# Container healthcheck status:
docker inspect quiz-backend --format '{{.State.Health.Status}}'
```

The Compose `healthcheck` block on `quiz-backend` calls `/api/health`
every 30s; `quiz-frontend` waits for `service_healthy` before starting.

---

## 4. Incident scenarios

### 4.1 "I get 401 on every request"

Cause: `API_TOKEN` is set on the backend but the browser hasn't
saved it.

Fix:
1. Open `Settings → API 認証トークン` in the SPA.
2. Paste the value used in the backend env (`docker exec quiz-backend env | grep API_TOKEN`).
3. Click 保存. The axios interceptor and `useSSE` will attach
   `Authorization: Bearer <token>` to all subsequent calls.

If you don't want auth at all, restart the backend with `API_TOKEN`
unset.

### 4.2 "Scraping fails with 422 — プライベート/ループバック..."

Cause: the URL resolves to a private IP. This is the
deny-by-default SSRF policy from P0-4.

Options (pick the smallest):

- The URL is genuinely public — check that `dig +short <hostname>` does
  not return RFC1918. If a CDN returns mixed answers, the strict policy
  rejects the whole set.
- The URL is intentionally on your LAN — restart the backend with
  `ALLOW_PRIVATE_NETWORKS=1`. Cloud metadata IPs remain denied.
- The URL uses `http://` and you don't want to upgrade — restart with
  `ALLOW_HTTP=1`. This downgrades the security posture; document
  internally if you do this.

### 4.3 "Ollama disconnected" in the navbar

```bash
# Is the host process up?
ollama list  # should print the installed models

# Can the backend reach the host on the configured URL?
docker exec quiz-backend curl -s "$OLLAMA_BASE_URL/api/tags"

# On Linux hosts, host.docker.internal may not resolve. Use a route:
docker exec quiz-backend cat /etc/hosts | grep host.docker.internal
# If empty, restart with: OLLAMA_BASE_URL=http://172.17.0.1:11434
```

### 4.4 SQLite corruption / WAL leftovers

Symptoms: `database disk image is malformed` in the backend log.

```bash
# Stop writers first.
docker compose stop backend

# Inspect from inside the container so paths line up.
docker compose run --rm backend bash -c \
    "sqlite3 /app/.cache/quizgen.db 'PRAGMA integrity_check;'"

# If integrity_check returns errors, recover by dumping + reloading:
docker compose run --rm backend bash -c \
    "sqlite3 /app/.cache/quizgen.db .dump > /app/.cache/recover.sql && \
     mv /app/.cache/quizgen.db /app/.cache/quizgen.db.broken && \
     sqlite3 /app/.cache/quizgen.db < /app/.cache/recover.sql"

docker compose start backend
```

The `quiz-cache` volume is the one that matters — back it up with
`docker run --rm -v quiz-app_quiz-cache:/data -v $PWD:/out ubuntu \
    tar -czf /out/quiz-cache-$(date +%F).tar.gz -C /data .`.

### 4.5 "Generation hangs at 1 / N"

Causes (in likelihood order):

1. Ollama model is too large for available RAM. Check
   `GET /api/system/specs` against `ollama show <model>` and the
   capability warning banner the SPA shows.
2. Ollama is busy with another query. Watch `ollama ps`.
3. The scraped content is empty (some sites detect headless browsers
   even via camoufox). Re-run with a different `depth` or use the
   plain-text source as a fallback.

The SPA exposes a 生成を中止 button while in-flight — that aborts the
fetch via `AbortController` and the backend stops the SSE generator
on the next yield boundary.

### 4.6 `Failed to resolve import "<pkg>"` after pulling new code

Symptom: Vite overlay in the browser:
```
[plugin:vite:import-analysis] Failed to resolve import "mermaid" from
"src/components/QuestionCard.vue". Does the file exist?
```
or backend log: `ModuleNotFoundError: No module named '<pkg>'`.

Cause: `docker-compose.dev.yml` mounts named volumes
(`frontend-node-modules`, `backend-packages`) over `/app/node_modules`
and `/usr/local/lib/python3.11/site-packages`. Those volumes survive
container recreation, so a `package.json` / `requirements.txt` update
in the *image* doesn't reach what the *container* actually sees.

Fix (no downtime, ~30s):

```bash
# Frontend:
docker exec quiz-frontend npm install
# Backend:
docker exec quiz-backend pip install -r requirements.txt
```

Then reload the browser tab — Vite's HMR re-resolves on the next
request and the overlay dismisses itself. Flask reloads automatically.

Alternative (heavier; rebuilds the volume from scratch — slow):

```bash
docker compose -f docker-compose.dev.yml down -v   # the -v wipes volumes
docker compose -f docker-compose.dev.yml up -d --build
```

`docker compose watch` (Docker Compose 2.22+) is set up to do the right
thing automatically when `package.json` / `requirements.txt` change —
the `develop.watch` blocks in `docker-compose.dev.yml` mark them as
`rebuild` triggers. If you run the dev stack with
`docker compose -f docker-compose.dev.yml watch` (instead of `up -d`),
this scenario does not occur in the first place.

### 4.7 Disk usage growing on `/app/.cache`

```bash
# Sizes by table:
docker exec quiz-backend python -c "
import sqlite3
c = sqlite3.connect('/app/.cache/quizgen.db')
for tbl in ('documents', 'quiz_sessions'):
    n = c.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
    print(f'{tbl}: {n} rows')
"

# Manual purge of old quiz_sessions (before 2026-01-01):
docker exec quiz-backend sqlite3 /app/.cache/quizgen.db \
    "DELETE FROM quiz_sessions WHERE generated_at < '2026-01-01';"
```

A formal retention policy is tracked as `[PLANNED: S-015]` in
SECURITY.md.

---

## 5. Updating

### 5.1 Routine update from `main`

```bash
git fetch origin && git pull --ff-only
docker compose -f docker-compose.dev.yml up -d --build
# OR for prod-like:
docker compose up -d --build

# Verify all CI green commits made it:
docker exec quiz-backend python -m pytest tests/ -q   # 72 expected
```

### 5.2 Bumping a Python dep

```bash
# 1. Edit backend/requirements.txt with the new pin.
# 2. Locally:
pip install -r backend/requirements.txt
python -m pytest backend/tests/ -q
pip-audit -r backend/requirements.txt --strict
# 3. Push branch — CI will re-run pip-audit + pytest as a hard gate.
```

### 5.3 Bumping a Node dep

```bash
cd frontend
npm install --save-exact <pkg>@<version>
npm audit --omit=dev --audit-level=moderate
npx vite build           # smoke
npx playwright test      # smoke
git add package.json package-lock.json
```

---

## 6. Monitoring (recommendations, not implemented)

For ad-hoc local use the existing logs are enough. If you ever expose
the service further, wire these signals into something like Loki or
Vector before doing so:

| Signal                                   | Source                                | Why it matters |
|------------------------------------------|---------------------------------------|----------------|
| `Detected change in '...', reloading`    | backend stdout (Flask)                | Reload loop = config drift |
| `API_TOKEN が未設定のままネットワーク公開されています` | backend startup            | Highest-impact misconfig |
| `[camoufox] URL拒否`                     | backend warning                       | Indicates someone is probing SSRF |
| `クラウドメタデータエンドポイント...`         | backend warning (UnsafeURLError)      | High-severity SSRF probe |
| 401 spike on `/api/*`                    | reverse proxy access log              | Token churn or attempted brute force |
| pip-audit / npm audit non-zero in CI     | GitHub Actions                        | New CVE against pinned dep |
| Playwright e2e failure                   | GitHub Actions                        | Frontend contract regression |

---

## 7. Recovery from a known-bad commit

```bash
# Identify the broken commit:
git log --oneline -10

# Fast-revert:
git revert --no-edit <bad-sha>
git push origin main

# CI will rebuild + reverify on the revert commit. The compose stack
# will pick up the change on the next `docker compose up -d --build`.
```

If `main` is ahead of CI green (e.g. a force-merge):

```bash
git reset --hard <last-known-green-sha>
git push --force-with-lease origin main   # requires explicit consent
```

`--force-with-lease` is intentional: it refuses to overwrite work the
remote has accepted since you fetched. Document the reason in the
commit / PR body.
