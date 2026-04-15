# Contributing

This is a single-maintainer hobby project, so the rules are tuned for
keeping change reviewable rather than scaling to a team. The hardening
roadmap (Phase 0 → Phase 3) introduced strict gates that contributors
should respect.

Last updated **2026-04-15**.

---

## 1. Branch and commit conventions

### Branches

```
main                              # protected; only fast-forward / merge --no-ff
feature/<area>/<short-slug>       # new behavior
fix/<area>/<short-slug>           # bug fix
hotfix/<short-slug>               # production hot patch
chore/<short-slug>                # tooling / docs only
```

The hardening pass used `feature/hardening/<phase-id>-<slug>`, which is
the recommended naming for follow-ups (e.g.
`feature/hardening/p3-runbook-rev2`).

Direct commits to `main` are blocked by a local guard hook
(`~/.claude/hooks/guard-gitflow.sh`). Use `git merge --no-ff` from a
feature branch.

### Commits

- One logical change per commit. Mixing a refactor with a bugfix is a
  CI-failure waiting to happen — split.
- Subject in the imperative, ≤ 70 chars: `fix(backend): bound parser memory`.
- Body explains the *why*, not the *what*. The hardening commits in
  `git log --grep=hardening` are good templates.
- Every meaningful commit references its tracking ID (`P0-4`, `S-011`,
  etc.) so the audit trail stays grep-able.

### Pull requests

For this repository PRs and merge commits are equivalent — both go
through `git merge --no-ff`. Open a PR when:

- The change is large enough to want diff review on the GitHub UI.
- The change crosses two areas (e.g. backend + frontend).
- You want CI to run before touching `main` (push the branch, GitHub
  Actions runs the same workflow as `main`).

---

## 2. Local development

### Prerequisites

- Docker + Docker Compose
- Ollama installed and running on the host (`ollama serve`)
- Node 22.x for running Playwright tests outside Docker
- Python 3.11.x for running pytest outside Docker

### Start

```bash
cp .env.sample .env             # only if you want to override CORS_ORIGINS or OLLAMA_BASE_URL
docker compose -f docker-compose.dev.yml up -d --build
```

Bind mounts hot-reload `src/` (Vite HMR) and `app/` (Flask `--debug`).
The compose file uses `usePolling` for Vite and `PollingObserver` for
watchdog so WSL2 file events behave reliably.

### Stop

```bash
docker compose -f docker-compose.dev.yml down
# Add -v if you want to wipe the SQLite + node_modules volumes too.
```

---

## 3. Running tests

### Backend (pytest)

```bash
# All:
python -m pytest backend/tests/ -q

# A single file:
python -m pytest backend/tests/test_safe_fetch.py -v

# Just the SSRF DNS-rebinding cases:
python -m pytest backend/tests/test_safe_fetch.py -k dns
```

`backend/tests/conftest.py` wipes `ALLOW_HTTP`, `ALLOW_PRIVATE_NETWORKS`,
`MAX_FETCH_BYTES`, `MAX_REDIRECTS`, `API_TOKEN` before each session so
tests start from the strict default. Set them per-test via
`monkeypatch.setenv(...)` if needed.

### Frontend (Vite build + Playwright)

```bash
cd frontend
npm ci                          # match the lockfile exactly
npm audit --omit=dev --audit-level=moderate
npm run build                   # smoke

# E2E (auto-spawns the dev server unless 1234 is taken):
npx playwright test
npx playwright test --headed    # see what's happening
npx playwright show-report      # last failure traces
```

The e2e suite mocks all `/api/*` calls (`frontend/e2e/_helpers.js`) so
no real backend or Ollama is needed.

---

## 4. CI gates (`.github/workflows/ci.yml`)

Every push to `main` and every PR runs four jobs in parallel:

| Job                       | Hard gate? | Catches                                      |
|---------------------------|------------|----------------------------------------------|
| `backend / pytest`        | yes        | Logic regressions, SSRF/auth/extractor breakage |
| `frontend / build + audit`| yes        | Bundle build failure; `npm audit` moderate+ |
| `deps / pip-audit`        | yes        | New CVE against any pinned Python dep        |
| `e2e / playwright`        | yes        | Frontend contract regressions (SSE, auth)    |

A red CI on `main` is an emergency — revert the offending merge
(`git revert <sha>` then push). Don't push fixes-on-top hoping the
next run will pass.

---

## 5. Adding new validation

Validation lives in two places:

- `backend/app/api/_schemas.py` (Pydantic V2) for **JSON request bodies**.
- `backend/app/api/_validation.py` (helpers) for **query parameters**.

When adding a new endpoint:

1. Define the body schema in `_schemas.py`. Reuse `ContentRequest`,
   `QuizGenerateRequest`, etc. by composition where possible.
2. In the route, do `try: req = MySchema.model_validate(body); except
   ValidationError as e: return jsonify({"error": humanize_first_error(e)}), 400`.
3. Add a happy-path + at least one error-path case to
   `backend/tests/test_schemas.py`.
4. If the endpoint takes user-supplied URLs, route them through
   `safe_fetch.safe_get` — never call `requests.get` / `urllib.urlopen`
   directly.

---

## 6. Adding new endpoints

Cross-reference: [`docs/architecture.md`](../architecture.md) §2 lists
every existing endpoint. Update it when you add another.

Checklist:

- [ ] Body schema in `_schemas.py` (or query helpers in `_validation.py`).
- [ ] Auth-exempt? Add to `_AUTH_EXEMPT_PATHS` in `security.py` only if
      it returns no privileged data (e.g. health probes).
- [ ] Test in `backend/tests/test_security.py` if auth posture changes.
- [ ] Update `docs/architecture.md` table.
- [ ] Update `README.md` API reference (both English and Japanese sections).
- [ ] Update `frontend/e2e/_helpers.js#mockBackend` so e2e tests still
      get a non-network response.

---

## 7. Adding a frontend store / API call

- HTTP calls go through the axios instance in
  `frontend/src/composables/useApi.js` so the request interceptor can
  attach the `Authorization` header.
- SSE consumers go through `streamSSE` in
  `frontend/src/composables/useSSE.js`. Do not introduce raw `fetch` or
  `EventSource` in stores.
- Pinia stores live in `frontend/src/stores/index.js`. Keep them
  domain-flat (one store per resource) and avoid cross-store imports.

When adding a new SSE event from the backend, update both:
- the backend `_sse_event(...)` site,
- the frontend store's switch statement,
- the README's SSE event contract table.

---

## 8. Local guard hooks (operator's CLAUDE.md setup)

The maintainer's environment runs PreToolUse hooks that block:

- `rm -rf` against system paths
- Reading `.env`, `.ssh`, `.aws`
- Direct commits to `main`/`develop`
- `git push --force` against `main` without explicit consent

If you're contributing from a different setup, replicate at least the
"no direct commit to main" rule via a Husky pre-commit hook or a
GitHub branch protection rule.

---

## 9. Filing a security report

Open a private GitHub Security Advisory:
<https://github.com/yuya4i/mock-exam/security/advisories/new>.

If that channel is unavailable, open a regular issue with the minimum
context needed to coordinate disclosure. See [`SECURITY.md`](../../SECURITY.md)
§9 for the full policy.
