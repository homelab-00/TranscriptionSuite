# Investigation: GH #202 — "Result too large to stream — fetch failed" on a 3-hour transcription

## Hand-off Brief

1. **What happened.** A user recorded a ~3-hour lecture on Apple Silicon (v1.3.7, macOS/MLX). On stop, the server transcribed the full recording, and because the result payload exceeded the 1 MB WebSocket inline limit, it sent a lightweight `result_ready` **reference** and told the client to fetch the full result over HTTP. The client's recovery fetch uses a **bare relative URL** (`fetch('/api/transcribe/result/{job_id}')`) that resolves against the packaged renderer's `file://` origin instead of the backend base URL (`http://localhost:9786`). The request never reached the server, so the client showed **"Result too large to stream — fetch failed"**.
2. **Where the case stands.** Root cause **confirmed** (adversarially verified — 0 of 3 refutation attempts succeeded). The transcript is **not lost** — it was persisted to the DB before the reference was sent and is protected from cleanup. A **second latent defect** was found: even after fixing the URL, the ownership check would `403` on the localhost-bypass path. Both must be fixed together. No code has been changed yet.
3. **What's needed next.** Implement the two-part fix (route both recovery fetches through `apiClient`'s base URL **and** reconcile the `localhost-user` ownership mismatch), add regression tests, and reply to the reporter with the manual DB-recovery steps so they can retrieve their lecture now.

## Case Info

| Field             | Value                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------ |
| Ticket            | #202                                                                                                   |
| Date opened       | 2026-07-11 (GH); investigation 2026-07-11                                                               |
| Status            | Root cause confirmed — fix not yet implemented                                                         |
| Labels            | `bug`, `apple-silicon-mlx` (the MLX label is **incidental** — see §7)                                   |
| System (report)   | Apple Silicon Mac, macOS (darwin), TranscriptionSuite v1.3.7 (Metal/MLX), Docker daemon NOT running     |
| Evidence sources  | Attached `client-debug.log` + `mlx-server.log`; dashboard/server source at main HEAD `2253166d`; git log |
| Severity          | **High** (user cannot retrieve a completed 3 h transcript in-app) — but **NOT data loss** (recoverable)  |
| Reproducibility   | Deterministic for any **packaged** build whose result payload exceeds **1 MB** (≈ >30–45 min of speech)  |

## Problem Statement

The reporter recorded a ~3-hour lecture. After stopping, the **Main Transcription** panel displayed:

> Result too large to stream --fetch failed

That exact string is the client's own error text (`dashboard/src/hooks/useTranscription.ts:259` and `:264`), emitted when the HTTP recovery fetch for a large result returns non-200 or throws.

---

## 1. Timeline (reconstructed from the two logs, UTC)

| Time (UTC)        | Source                     | Event |
| ----------------- | -------------------------- | ----- |
| 11:12:44          | client-debug.log           | App start; **packaged** build — stack traces show `file:///Applications/TranscriptionSuite.app/…/app.asar/…` (client-debug.log:52) |
| 11:13:02          | client-debug.log           | Main WS connects to `ws://localhost:9786/ws`, `session_started` |
| 11:13:09 → 14:24  | client-debug.log           | **Live Mode** runs ~3 h 11 m (`SocketLive` `sentence`/`state` stream) |
| 14:24:22          | client-debug.log           | `=> stop` |
| 14:24:31          | client-debug.log           | `<= session_stopped` — server begins the **longform (Main) transcription** of the full recording |
| 14:24:36 → 14:29:26 | client-debug.log          | `<= processing_progress` every 5 s (~5 min of longform processing) |
| 14:29:31.548Z     | mlx-server.log:2040        | `Transcription completed … 1606 segments` |
| 14:29:31.894Z     | mlx-server.log:2042        | `Ended transcription job 39378f14…` (result persisted to DB) |
| 14:29:31.895Z     | client-debug.log:388       | `<= result_ready` — server sent the **reference** (payload > 1 MB) |
| 14:29:31.904Z     | client-debug.log:389       | Client `Disconnect requested`; the relative recovery fetch is issued and **fails at the `file://` layer** |
| 14:29–14:31+      | mlx-server.log:2068–2069   | Same renderer's **apiClient** calls (`/api/notebook/calendar`, `/api/transcribe/languages`) reach the server 200 OK — proving the server was alive and reachable |

**Decisive observation:** `mlx-server.log` contains **zero** `GET /api/transcribe/result/...` lines (only `/api/status` ×416, `/api/admin/status` ×424, `/api/transcribe/languages`, `/api/notebook/calendar`). The recovery request was never emitted as an HTTP request to the backend, while other renderer→backend HTTP calls in the same window succeeded.

---

## 2. Root Cause (primary)

**The large-result recovery fetch uses a root-relative URL that bypasses the configured API base URL, so in a packaged build it resolves to the renderer's `file://` origin and never reaches the backend.**

Server side — the "too large → send a reference" path (correct, durability-safe):

```python
# server/backend/api/routes/websocket.py:391-425
_save_result(job_id=..., result_text=..., result_json=json.dumps(result_payload, ...), ...)  # PERSIST BEFORE DELIVER
...
_result_size = len(json.dumps(result_payload))
if _result_size > 1_000_000 and self._current_job_id:
    await self.send_message("result_ready", {"job_id": self._current_job_id})   # reference, NOT inline
    _sent_as_reference = True
else:
    await self.send_message("final", result_payload)                             # inline
# mark_delivered is intentionally skipped for the reference path
```

Client side — the broken recovery fetch:

```ts
// dashboard/src/hooks/useTranscription.ts:245 (result_ready handler)
fetch(`/api/transcribe/result/${job_id}`, { headers: authHeader })   // ← RELATIVE
  ...
  .catch(() => setError('Result too large to stream — fetch failed'));  // :264
```

Every other client HTTP call goes through `apiClient`, which prepends the base URL:

```ts
// dashboard/src/api/client.ts:225  (baseUrl default 'http://localhost:9786', :100)
const res = await fetch(`${this.baseUrl}${path}`, { ... });
```

**Mechanism.** In a packaged build the renderer is loaded from disk, not a web server:

- `dashboard/electron/main.ts:121` — `const isDev = !app.isPackaged`
- `dashboard/electron/main.ts:861` — production branch: `mainWindow.loadFile('.../dist/index.html')` → origin is `file://`
- `dashboard/vite.config.ts:157-158` — `base: './'` ("Use relative paths so Electron can load from file:// protocol")
- No custom protocol/proxy is registered (grep for `protocol.handle`/`registerSchemesAsPrivileged`/`webRequest`/`<base>` → 0 matches)

So `fetch('/api/transcribe/result/{id}')` resolves to `file:///api/transcribe/result/{id}`. Chromium rejects a `fetch()` of a `file://` URL (default `webSecurity` is on — `main.ts:799-804` does not disable it), the promise rejects into `.catch()`, and the user sees the error. **The WebSocket works** in the same session only because `getWsUrl()` builds an **absolute** `ws://localhost:9786/ws` from `apiClient.getBaseUrl()` (`dashboard/src/services/websocket.ts:176-181`) — the exact asymmetry that isolates the defect.

The same relative-URL defect exists at a **second call site** — the onClose disconnect-poll fallback (`useTranscription.ts:370`). In this incident only the `result_ready` handler fired (it nulls `jobIdRef` at `:271` before disconnect, so the poll loop is skipped), but both paths are broken identically.

---

## 3. Secondary defect — ownership `403` on the localhost-bypass path (would block the fix)

Fixing the URL alone is **not sufficient**. The WebSocket authenticated via the **localhost bypass**, which hardcodes the job's owner:

```python
# server/backend/api/routes/utils.py:198-204  (WS auth, localhost + non-TLS)
if allow_localhost_bypass and not TLS_MODE and is_local_auth_bypass_host(client_host):
    return WebSocketAuthResult(client_name="localhost-user", is_admin=True, is_localhost_bypass=True, stored_token=None)
```

So the persisted job's `client_name = "localhost-user"`. But the HTTP result endpoint derives the caller identity from the **token only** — there is no localhost bypass:

```python
# server/backend/api/routes/utils.py:292-302
def get_client_name(request: Request) -> str:
    stored_token = validate_auth_token(get_request_auth_token(request))
    if stored_token:
        return stored_token.client_name
    return "Unknown Client"
```

And the endpoint enforces ownership:

```python
# server/backend/api/routes/transcription.py:1408-1410
client_name = get_client_name(request)
if job.get("client_name") is not None and job["client_name"] != client_name:
    raise HTTPException(status_code=403, detail="Access denied")
```

`get_client_name()` cannot return `"localhost-user"` (the bypass sets `stored_token=None` and creates no such token), so `job["client_name"] ("localhost-user") != client_name` → **403 Access denied**. The same `client_name` mismatch also means `GET /api/transcribe/recent` (`transcription.py:1759`, queries `get_recent_undelivered(client_name, …)`) would **not** surface the job. Both the direct fetch and the recovery-notification list would remain broken for localhost-bypass users until this identity inconsistency is reconciled.

---

## 4. Data safety & recoverability (severity)

**This is a delivery/retrieval bug, not data loss.** The result is persisted to the DB **before** any delivery attempt:

- `server/backend/api/routes/websocket.py:391-399` — `_save_result(...)` writes `result_text` (full transcript) and `result_json` (full payload incl. words) with `status='completed'`, *before* the size check.
- The reference path deliberately **skips** `mark_delivered`, so the row is `status='completed', delivered=0`.
- The row is **protected**: orphan recovery only touches `status='processing'` (`job_repository.py:334-360`); cleanup only deletes `status='completed' AND delivered=1` (`job_repository.py:363-392`). A `completed/delivered=0` row is neither purged nor its audio deleted.

**But no working in-app surface can retrieve it**, because every retrieval path is broken by §2 (and §3):

| Retrieval surface | Location | Broken by |
| ----------------- | -------- | --------- |
| `result_ready` fetch | `useTranscription.ts:245` | relative URL (§2) + `403` (§3) |
| onClose poll loop | `useTranscription.ts:370` | relative URL (§2) + `403` (§3) |
| Recovery notification list | `SessionView.tsx:1059` (`/api/transcribe/recent`) | relative URL + `client_name` mismatch (§3) |
| Recovery "View" / "Dismiss" | `SessionView.tsx:1255`, `:1281` | relative URL (§2) + `403` (§3) |
| Notebook / Recordings view | uses `apiClient` (absolute) — would work | but the **longform WS flow never creates a notebook `recordings` row** (`save_longform_to_database` is only called from `notebook.py:1140`, never from `websocket.py`) |
| Retry | `transcription.py:1462-1469` | only accepts `status='failed'`; this job is `completed` → 409 |

**Immediate recovery for the reporter (no code change):** read the row directly from SQLite at `<data_dir>/database/notebook.db` (`database.py:40,60-67`):

```sql
SELECT result_text, result_json
FROM transcription_jobs
WHERE status='completed' AND delivered=0
ORDER BY completed_at DESC LIMIT 5;
```

`result_text` alone contains the full plain transcript.

---

## 5. Why "Main Transcription" and why 3 hours specifically

The user ran **Live Mode**, but the error is on the **Main Transcription** because on stop the server runs a full longform pass over the entire recording and returns it via the main WS (`processing_progress` → `result_ready`). Only results **over 1 MB** take the reference path (`websocket.py:415-417`); the payload is the full `result.to_dict()` with per-word/segment timestamps (`websocket.py:_build_longform_result_payload`). A ~3 h transcript (~27k words) comfortably exceeds 1 MB, so it hits the broken path; shorter recordings stay under the threshold and use the working inline `final` path — which is why this was never seen before.

---

## 6. Contributing factors

- **Never absolute.** The fetches were born relative and stayed relative (see §8). A later "13 code-review patches" commit added auth headers to both sites but left the URLs relative.
- **Dev masks it.** Dev loads the renderer from `http://localhost:3000` (`main.ts:844`), where a root-relative `/api` at least forms an `http://` URL; and there is **no Vite dev proxy** (0 matches for `proxy` in `vite.config.ts`), so the failure mode differs from prod.
- **Rarely exercised.** The >1 MB path requires a multi-hour transcript — essentially never produced in routine dev/QA.
- **Two independent latent bugs stacked** (relative URL + ownership mismatch), so a single-pass fix of the visible symptom would still leave the feature broken.

---

## 7. Is this Apple-Silicon/MLX specific? No.

The `apple-silicon-mlx` label is **incidental** (it's simply the reporter's platform). The failing code is entirely in the **shared** renderer bundle and the **shared** FastAPI backend:

- The MLX server runs the *same* app: `mlxServerManager.ts:189` spawns `uvicorn server.api.main:app` — identical routers, port model (9786), and auth as Docker.
- The renderer origin is `file://` on **all** platforms in packaged builds (`main.ts:861`).
- No MLX-vs-Docker CSP/header differences exist (0 matches for CSP customization in `dashboard/electron/`).

**A Docker packaged client (Windows/Linux/Intel-Mac) producing a >1 MB result would fail identically.** Recommend relabeling as a general packaged-build bug.

---

## 8. Git origin & fix location

Both fetches were introduced **relative** and never made absolute (all ancestors of HEAD `2253166d`):

| Call site | Introduced by | Notes |
| --------- | ------------- | ----- |
| onClose poll (`:370`) | `9d07247f` "feat: Wave 1 transcription durability — never lose a completed result" (2026-03-30) | first form already relative |
| `result_ready` (`:245`) | `654e19d3` "feat: Wave 3 transcription recovery — orphan jobs, graceful drain, large results" (2026-03-30) | first form relative, no auth |
| (both) | `08333f91` "fix: Apply 13 code review patches…" | added `Authorization` headers, **kept URLs relative** |

Only these two sites reference `transcribe/result` in the entire dashboard.

---

## 9. Recommended fix (two parts — both required)

**Part A — route the recovery fetches through the configured base URL.** `apiClient` is already imported (`useTranscription.ts:12`) and used for `getAuthToken()` at both sites. Prefer a dedicated method for consistency with the rest of `client.ts`:

```ts
// dashboard/src/api/client.ts — new method (reuses ${this.baseUrl}${path} + auth pattern)
async getTranscriptionResult(jobId: string): Promise<Response> {
  const token = this.getAuthToken();
  return fetch(`${this.baseUrl}/api/transcribe/result/${jobId}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}
```

Replace the raw `fetch(...)` at `useTranscription.ts:245` and `:370` (and the three relative fetches in `SessionView.tsx:1059/1255/1281`) with base-URL-prefixed calls.

**Part B — reconcile localhost-bypass identity so the owner can read their own job.** Options (pick one, add a test):
- Give `get_client_name()` the same localhost + non-TLS bypass as the WS auth (return `"localhost-user"` for local, token-less requests), **or**
- In the ownership check (`transcription.py:1408-1410`) and `get_recent_undelivered`, treat a localhost, non-TLS request as owner of `"localhost-user"` jobs.
  Ensure `GET /recent` returns localhost-bypass jobs for the same caller.

**Optional hardening.** Consider streaming/chunking large results, or raising the 1 MB inline threshold, so the recovery path is exercised less; but the recovery path must be correct regardless.

---

## 10. Regression tests to add

- **Frontend:** assert the `result_ready` handler and onClose poll issue an **absolute** URL (`http://localhost:9786/api/transcribe/result/…`), e.g. by asserting `fetch` was called with a URL starting with `apiClient.getBaseUrl()`. Guards against reintroducing a relative URL.
- **Backend (route test, direct-call pattern per CLAUDE.md):** a job owned by `"localhost-user"` must be retrievable via `GET /result/{job_id}` and appear in `GET /recent` for a localhost, non-TLS caller (currently 403 / absent). Extends `tests/test_p0_durability.py` which already covers `result_ready` reference + not-marked-delivered.

---

## 11. Verification method (how this RCA was confirmed)

A structured RCA workflow ran **5 parallel investigators** (renderer origin, recoverability, alternative hypotheses, git archaeology, MLX-label validity) followed by **3 adversarial refutation agents** each instructed to *break* the root cause via (a) the logs, (b) URL resolution, (c) an alternative cause. **All 3 returned `refuted: false`** (refutedCount = 0). Alternatives ruled out with evidence: auth 401/403 (would still produce a server log line — none exists), CSP (`index.html:8` whitelists `http://localhost:*`), WS-close race (fetch has no `AbortController` tied to the socket), URL-encoding, and the 1 MB threshold (correct trigger, not a fault). The one alternative that survived as a *real* issue is the §3 ownership `403`, retained as a secondary defect rather than the primary cause.
