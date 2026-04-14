# Security Policy

> **Status**: Hardening pass in progress (Phase 0). This document reflects the
> *intended* security posture for the current and upcoming phases, and
> explicitly calls out capabilities that are **not yet enforced in code**.
> Every unenforced item is marked `[PLANNED]` and tracked by an ID.

---

## 1. Scope & supported versions

QuizGen is a single-host, Docker Compose application that:

- runs a Flask API (`backend/`) and a Vue 3 SPA (`frontend/`),
- calls a local Ollama instance for LLM inference,
- scrapes arbitrary user-supplied URLs via Camoufox or a `requests` fallback,
- persists state in SQLite.

Only the `main` branch is supported. There is no backport policy.

---

## 2. Deployment posture

This project is intended for **trusted local / LAN use only**.

> **Not for unrestricted internet exposure without additional controls.**

Specifically, the default configuration:

- has **no authentication** on any `/api/*` endpoint,
- binds containers to `0.0.0.0` (reachable from the host LAN),
- allows arbitrary outbound URL fetches (post Phase 0 hardening: restricted to
  public IPs only — see §4),
- runs the LLM against **untrusted scraped content** (prompt injection channel —
  see §5).

If you expose this service beyond `127.0.0.1`, you MUST add at minimum:

1. a reverse proxy that enforces authentication (mTLS, OIDC, or basic-auth),
2. network egress controls (block outbound to private RFC1918/link-local/
   metadata endpoints at the host or container network level),
3. rate limiting / abuse controls per remote IP,
4. disk-quota and retention controls on the SQLite volume.

---

## 3. Trust boundaries

```
[Browser ]──HTTP/SSE──▶[Flask API]──▶[ContentService]──HTTP/S──▶[Arbitrary external sites]
                           │                 │
                           │                 └─bytes─▶[pypdf / csv / BeautifulSoup]─▶[SQLite]
                           │
                           └──▶[Ollama /api/chat]──▶[LLM output]──▶[SSE]──▶[Browser]
```

Every arrow crossing a boundary MUST be treated as untrusted:

| Boundary                                   | Input                              | Current validation                                     |
|--------------------------------------------|------------------------------------|--------------------------------------------------------|
| Browser → Flask                            | JSON body / query params           | Partial (Phase 0 tightens it) — see issue `R-001..R-004` |
| Flask → ContentService (URL)               | user-supplied URL                  | Phase 0: scheme + IP allowlist — see §4                |
| ContentService → external HTTP             | user-supplied URL                  | Phase 0: redirect cap + size cap — see §4              |
| External bytes → pypdf / csv / lxml        | hostile file                       | Partial (page/row caps); zip-bomb class attacks NOT covered on pypdf `[PLANNED: S-011]` |
| Scraped content → Ollama prompt            | attacker-controlled text           | Not sanitized — prompt injection channel — see §5      |
| Ollama → Flask → Browser (SSE)             | LLM output                         | JSON-shape check only; rendered as text except `diagram` which passes through mermaid.js sanitizer |
| Browser `v-html="diagramSvg"`              | mermaid-rendered SVG               | Trusted iff the mermaid render path is trusted (see §6) |

---

## 4. Outbound URL fetch policy

Implemented by `backend/app/services/safe_fetch.py` (introduced in
`feature/hardening/p0-4-ssrf-safe-fetch`).

### Defaults (deny-by-default)

| Check                         | Behavior                                                                           |
|-------------------------------|------------------------------------------------------------------------------------|
| Scheme                        | `https` allowed. `http` **denied** unless `ALLOW_HTTP=1`.                          |
| Hostname                     | Resolved via `socket.getaddrinfo`. **All** resolved IPs must be public.            |
| Private ranges denied         | RFC1918, loopback (`127.0.0.0/8`, `::1`), link-local (`169.254/16`, `fe80::/10`), multicast, reserved, unspecified (`0.0.0.0`, `::`). |
| Cloud metadata endpoints      | `169.254.169.254`, `100.100.100.200`, `fd00:ec2::254` explicitly denied, **even if** `ALLOW_PRIVATE_NETWORKS=1`. |
| Redirect cap                  | `3` redirects max.                                                                 |
| Per-request timeout           | `(5s connect, 30s read)` default.                                                  |
| Per-request size cap          | `10 MiB` default (configurable via `MAX_FETCH_BYTES`).                            |
| User-Agent                    | Static identifiable UA; robots.txt is **not** honored automatically.              |

### Opt-in overrides

| Env var                       | Effect                                                              |
|-------------------------------|---------------------------------------------------------------------|
| `ALLOW_HTTP=1`                | Allow `http://` URLs in addition to `https://`.                    |
| `ALLOW_PRIVATE_NETWORKS=1`    | Allow RFC1918 / loopback / link-local. Cloud metadata IPs remain denied. |
| `MAX_FETCH_BYTES=<int>`       | Override per-request byte cap.                                     |
| `MAX_REDIRECTS=<int>`         | Override redirect cap (`0` disables redirects).                    |

> Setting these env vars weakens the security posture. Do not set them in
> production or on hosts that have network access to cloud metadata services,
> internal admin panels, or unprotected databases.

### Residual risk

- **DNS rebinding** is mitigated at resolve-time by re-checking the IP, but a
  sufficiently capable attacker could still race the re-resolve at connect-time.
  For high-value deployments, bind the backend to a network namespace that has
  no route to RFC1918.
- `camoufox` (Firefox) issues its own DNS; the guard validates the hostname
  before handing off, but Firefox may re-resolve. Treat camoufox fetches as
  **best-effort** SSRF protection, not authoritative.

---

## 5. Prompt injection & LLM output handling

The pipeline feeds **attacker-controllable text** (scraped HTML/PDF/CSV body)
directly into the system prompt via `quiz_service.SINGLE_Q_TEMPLATE`. There is
no current mitigation for prompt injection. Known-good mitigations and their
current status:

| Mitigation                                   | Status                      |
|----------------------------------------------|-----------------------------|
| Content length cap                           | Implemented (`MAX_CONTENT_CHARS=12000`) |
| Structural separator + explicit "ignore everything inside the following block" pattern | `[PLANNED: S-012]` |
| Content attribution in prompt ("source: <url>") | Implemented                 |
| Output schema validation (reject questions whose `answer` is not `a/b/c/d`, etc.) | Partial — `_parse_single_question` only type-checks `dict` and `"question" in q`; `[PLANNED: S-013]` full schema |
| Frontend text-only rendering                 | Implemented for `question` / `explanation` / `source_hint`; `diagram` goes through mermaid |

### LLM-driven `source_hint` and `pages[].url`

`<a :href="sourceLink">` in `QuestionCard.vue` validates the top-level
`source` scheme but not `pages[].url`. A future fix (`[PLANNED: S-014]`) will
validate both.

### Mermaid

`mermaid.render()` returns an SVG that is embedded via `v-html`. We rely on
mermaid's built-in sanitization. Pinning mermaid to a specific version
(`feature/hardening/p0-9-mermaid-local`) makes this boundary auditable.

---

## 6. Authentication & authorization

**Current state (P1-A + P1-G)**:

- Opt-in `API_TOKEN` env var. When set, all `/api/*` requests must include
  `Authorization: Bearer <token>`. When unset, the API remains open for local
  dev.
- Startup warning when the backend binds non-loopback addresses without
  `API_TOKEN`.
- Comparison uses `hmac.compare_digest` (constant-time).
- `/api/health` is the only exempt path so monitoring probes work without
  credentials.
- The browser SPA stores the token in `localStorage` (configured via
  `Settings → API 認証トークン`) and sends it via the `Authorization`
  header on every call — including the two SSE endpoints, which the
  frontend now consumes via `fetch` + ReadableStream rather than
  `EventSource`. Tokens never appear in URLs.

**Operator notes**:

- Do NOT store the token in `.env` that is committed; use
  `docker compose --env-file` or a secrets manager.

---

## 7. Data handling

| Data class                    | Storage                                    | Retention                           |
|-------------------------------|--------------------------------------------|-------------------------------------|
| Scraped documents             | SQLite `documents` table + in-container volume | No automatic purge `[PLANNED: S-015]` |
| Quiz sessions / answers       | SQLite `quiz_sessions` table               | No automatic purge                  |
| Legacy JSON history           | `history.json` in container volume         | `MAX_HISTORY=100` (oldest pruned)   |
| Ollama model weights          | Host (outside container)                   | Managed by user                     |
| Logs                          | Container stdout                           | Managed by Docker log driver        |

No PII is intentionally collected. Scraped URLs and their content may, however,
contain whatever the user submits. Treat the SQLite volume as sensitive.

---

## 8. Known limitations

- `HistoryService` and the SQLite `quiz_sessions` table are written **in
  parallel**. A failure in one path does not roll back the other. This will be
  consolidated to a single source of truth in Phase 1 (`M-006`).
- `_download_file` in Phase 0 uses the hardened `safe_fetch` client; however,
  `camoufox` in Phase 0 only validates URLs before `page.goto`. In-page JS that
  triggers further navigation is not intercepted.
- Container images in Phase 0 may still run as `root` for the `camoufox` path;
  non-root is tracked in `feature/hardening/p0-7-non-root-docker`.
- There is no CI, no dependency audit, no container scan in Phase 0. Tracked in
  Phase 1/2.

---

## 9. Reporting a vulnerability

Please open a **private** security advisory on the GitHub repository:
`https://github.com/yuya4i/mock-exam/security/advisories/new`.

If that channel is unavailable, open a regular issue with the **minimum** detail
needed to coordinate disclosure; the maintainer will reply with a private
contact.

Please do **not**:

- post working exploits against live third-party sites using this tool,
- test SSRF against cloud metadata endpoints of providers you do not own,
- fuzz public scraping targets without the target's consent.

---

## 10. Change log

| Date (UTC) | Change |
|------------|--------|
| 2026-04-14 | Initial policy introduced as part of Phase 0 hardening pass. |
