---
sprint: 5
date: 2026-05-04
project: TranscriptionSuite
issue: 104
epic_set: [epic-webhook (E7) Stories 7.1–7.7]
prereq: Sprints 1–4 merged (gh-104-prd HEAD)
budget_dev_days: 7–9
target_loc_ceiling: ≤2500 LOC (sprint prompt cap — smallest sprint)
ac_overrides_required: yes (URL-prefix on retry endpoint, snapshot-source for webhook payload, single-table reuse vs. new fan-out)
---

# Sprint 5 — Webhook Delivery (`webhook_deliveries` + `WebhookWorker` + payload v1) Design

This sprint implements 7 stories that share one persistent table
(`webhook_deliveries`), one background coordinator (`WebhookWorker`),
and one shared HTTP-delivery contract. The whole sprint is gated by
**three** invariants — Persist-Before-Deliver (Sprint 4 backbone, applied
again to webhook attempts), the SSRF security baseline (private-IP block
+ scheme allowlist + no redirects + no decompression), and the
"sweeper-recovers-on-restart" property already established by the
deferred-export sweeper.

The "central insight" of Sprint 5 is the same as Sprint 4 inverted again:
Sprint 4 was *artifact persistence* (summary text, export file). Sprint 5
is *attempt persistence* (the act of delivering, even if the delivery
fails). The `webhook_deliveries` row is the durable record that the
system **intended** to call out — it survives crashes, restarts, and
network outages so retry remains possible. Both ride on top of the
auto-action coordinator's escalation policy from Sprint 4 commit H —
webhook becomes a third action_type alongside `auto_summary` /
`auto_export`.

---

## 0. Sprint 1/2/3/4 prerequisite verification

Audit run before this design pass:

| Prerequisite | Path | Status |
|---|---|---|
| `profiles` table + `private_field_refs_json` | migration 008, `database/profile_repository.py` | PRESENT (Sprint 1) |
| `ProfilePublicFields` Pydantic model | `api/routes/profiles.py:62` | PRESENT (extend, don't rewrite) |
| `auto_action_repository` (status-column write helpers) | `database/auto_action_repository.py` | PRESENT (Sprint 4) |
| `auto_action_coordinator._handle_auto_action_failure` (escalation) | `core/auto_action_coordinator.py:380` | PRESENT (Sprint 4 commit H) — **Sprint 5 does not reuse this**; webhook has its own attempts column on `webhook_deliveries` |
| `retry_auto_action_internal` HTTP endpoint | `api/routes/notebook.py:1692` | PRESENT (Sprint 4 commit G) — **Sprint 5 extends `action_type` Literal to include `"webhook"`** |
| `audio_cleanup.periodic_cleanup` async-loop pattern | `database/audio_cleanup.py:18` | PRESENT (template for retention sweeper) |
| `auto_action_sweeper.periodic_deferred_export_sweep` | `core/auto_action_sweeper.py` | PRESENT (template for webhook retry sweeper IF needed) |
| `webhook_mock_receiver` aiohttp fixture | `tests/conftest.py:477` | PRESENT (Sprint 1) |
| `private_ip_resolver` getaddrinfo monkeypatch | `tests/conftest.py:426` | PRESENT (Sprint 1) |
| `flake8-tidy-imports.banned-api` rule on `httpx.AsyncClient` in tests | `pyproject.toml:140` | PRESENT — production code (`api/`, `core/`, `database/`) is exempt via per-file-ignores; tests must use `webhook_mock_receiver` |
| `AutoActionStatusBadge` + `useAutoActionRetry` | `dashboard/components/recording/`, `dashboard/src/hooks/` | PRESENT (Sprint 4) — Sprint 5 reuses both |
| `AudioNoteModal` recording-status wiring | `dashboard/components/views/AudioNoteModal.tsx:597` | PRESENT (Sprint 4) — extend with third badge |
| Migrations 008–015 in place | `database/migrations/versions/` | PRESENT (next free = **016**) |
| Existing legacy `core/webhook.py` global-config dispatcher | `core/webhook.py` | PRESENT (Sprint 0 baseline) — **left untouched**; new per-profile system coexists |

The legacy `core/webhook.py` is config-yaml-driven (single global URL,
fire-and-forget, no persistence). The new Sprint 5 work is *per-profile*
with a durable `webhook_deliveries` table. The two systems are
intentionally independent — the legacy one survives for backwards
compatibility with existing user setups.

---

## 1. Inline AC overrides (read first)

| AC literal text | Reality | Override |
|---|---|---|
| Story 7.5 AC1: webhook is a NEW action type "fired during the auto-action lifecycle or manually" | Sprint 4's `auto_action_coordinator.trigger_auto_actions` runs auto-summary + auto-export from `notebook.py::_run_transcription` (~line 1064). Adding webhook as a *third* coordinator branch couples the webhook to the same Persist-Before-Deliver fork. | The coordinator gains a third optional task — `_run_webhook_dispatch(recording_id, public)` — fired in parallel with auto-summary + auto-export when `public.get("webhook_url")` is set. The webhook task INSERTS into `webhook_deliveries` (its own table), then the **WebhookWorker** picks it up. We do NOT fire HTTP from inside the coordinator path — the coordinator only enqueues. This keeps the worker as the single delivery surface and lets the worker pick up sweeper-recovered rows the same way. |
| Story 7.7 AC1: retry endpoint accepts `action_type="webhook"` | Sprint 4 commit G's `AutoActionRetryRequest.action_type` Literal is `Literal["auto_summary", "auto_export"]`. | Extend to `Literal["auto_summary", "auto_export", "webhook"]`. The retry path branches: for `"webhook"` it does NOT call `retry_auto_action_internal` (that funnels to coordinator path). Instead it calls `webhook_worker.retry_delivery(recording_id)` which re-INSERTS a `webhook_deliveries` row with `status='pending'`. The worker picks it up on next tick. Same idempotency semantics: if the most recent row is already `success`, return `already_complete`. |
| Story 7.6 AC1: payload includes `transcript_url` and `summary_url` | The notebook URL shape is `/api/notebook/recordings/{id}/...`. There is no top-level `/api/recordings/{id}/transcript` endpoint. The "transcript URL" the receiver needs is the *retrieval* URL, not a path tail. | The payload uses the conventional REST shape: `transcript_url = f"/api/notebook/recordings/{recording_id}/segments"`, `summary_url = f"/api/notebook/recordings/{recording_id}"` (the GET that returns the row including the `summary` field). The receiver is expected to have the server's base URL out-of-band (it configured the webhook). |
| Story 7.2 AC2: scheme allowlist allows `http://localhost*` | `urlparse("http://localhost:8080/foo").hostname` returns `"localhost"`. The "starts-with" intent is to allow `http://localhost`, `http://localhost:5000`, `http://localhost.localdomain`. The first two are clear; the third is ambiguous. | Allow exactly `hostname == "localhost"` (case-insensitive) for `http://`. `http://localhost.localdomain` is NOT in the allowlist — out of scope for the local-dev override. Documented in the validator. |
| Story 7.2 AC3: server "resolves the URL hostname AND checks the IP" | `socket.getaddrinfo` is the canonical resolver; the `private_ip_resolver` fixture monkeypatches exactly this. But `getaddrinfo` can return MULTIPLE records (one A + one AAAA, multi-homed hosts). | Resolve via `socket.getaddrinfo(host, port, type=SOCK_STREAM)`, iterate ALL returned address records, reject if ANY of them is in the private/loopback ranges. This prevents DNS rebinding where the first record is public but a subsequent one is private. |
| Story 7.4 AC3: "explicitly does NOT request decompression and does NOT process the body" | `httpx` does NOT auto-decompress unless `Accept-Encoding` is sent AND the response includes `Content-Encoding`. By default httpx negotiates `gzip, deflate, br` via the `Accept-Encoding` request header. | Explicitly set `headers={"Accept-Encoding": "identity"}` so the server does not advertise compression support. Additionally, even if the server returns `Content-Encoding: gzip` anyway, do NOT call `response.read()` / `response.text` / `response.json()` — only the `status_code` is consulted. The body bytes are discarded without inflation. |
| Story 7.3 AC4: memory budget — `psutil.Process().memory_info().rss` p95 ≤ 50 MB | The pytest run already loads SQLAlchemy, FastAPI, and a chunk of the test infra into RSS. The 50 MB ceiling refers to the **delta** during the worker run, not absolute RSS. | Test samples baseline RSS BEFORE the worker starts, then computes `delta = sample - baseline` per tick. p95 of `delta` ≤ 50 MB AND linear-regression slope of `delta` over 60s ≈ 0 (no leak). The test runs only with `WEBHOOK_MEMORY_BUDGET=1` env var set so it doesn't gate normal CI runs. Documented in the test docstring. |
| Story 7.7 AC2: escalation per Story 6.11 (one auto-retry then manual) | `_handle_auto_action_failure` in `auto_action_coordinator` is auto-summary/auto-export-specific (writes to `auto_summary_status` columns). | Webhook escalation lives in `webhook_worker` itself, mirrors the same shape: first failure → schedule one delayed retry (30s) by inserting a fresh row with `status='pending'` after sleep; second failure → status flips to `manual_intervention_required`. We do NOT reuse `_handle_auto_action_failure` — coupling those tables would invert the abstraction. |

**Not an override but worth recording:** Sprint 5 introduces a NEW table
(`webhook_deliveries`), not new columns on `recordings`. Per-recording
webhook deliveries can be 1:N (one row per attempt), and rows survive
recording deletion intentionally so failure history is queryable for
debugging (NFR42). This contrasts with Sprint 4's auto-action columns,
which were 1:1 with the recording row.

---

## 2. Architectural through-lines

### 2.1 The Persist-Before-Deliver invariant (Story 7.5 backbone)

```
                          WebhookWorker tick
                                 │
                                 ▼
                   ┌────────────────────────────┐
                   │  INSERT webhook_deliveries │
                   │  status='pending'          │   ← committed first
                   │  payload=<json>            │
                   │  COMMIT                    │
                   └─────────────┬──────────────┘
                                 │
                                 ▼
                   ┌────────────────────────────┐
                   │  UPDATE status='in_flight' │   ← committed second
                   │  COMMIT                    │
                   └─────────────┬──────────────┘
                                 │
                                 ▼
                       httpx.AsyncClient.post
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
           UPDATE status='success'       UPDATE status='failed'
           last_attempted_at=NOW         last_error=<msg>
                                         attempt_count++
```

The chain is **strictly sequential** at the row level. A crash between
INSERT-pending and the HTTP call leaves a `pending` row that the worker
sweeps on next start (NFR17 / Story 7.5 AC2). A crash between
UPDATE-in_flight and the HTTP call leaves an `in_flight` row that is
*also* swept on next start — this could cause a duplicate POST if the
remote actually received the original. We accept this trade (durability
beats at-most-once for transcription-completion events), and document it.

**Test:** monkeypatch `sqlite3.Connection.commit` to raise on the second
commit (in_flight transition) — assert the row stays at `pending` and
the HTTP call is NOT issued.

### 2.2 The `webhook_deliveries` table (migration 016)

```sql
-- migration 016 — webhook delivery persistence
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id    INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    profile_id      INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
    status          TEXT NOT NULL CHECK (status IN (
                        'pending', 'in_flight', 'success',
                        'failed', 'manual_intervention_required'
                    )),
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_attempted_at TIMESTAMP,
    payload_json    TEXT NOT NULL  -- the body that was POSTed
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status
    ON webhook_deliveries(status) WHERE status IN ('pending', 'in_flight');

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_recording
    ON webhook_deliveries(recording_id);
```

**Status enum** (TEXT with CHECK — diverges from Sprint 4's "TEXT no
CHECK" pattern because the AC explicitly mandates the constraint at
table-create time):

| value | meaning |
|---|---|
| `pending` | written by the producer (coordinator or retry endpoint); not yet picked up |
| `in_flight` | worker has dequeued and is about to issue the HTTP call |
| `success` | 2xx response received |
| `failed` | non-2xx, timeout, or transport error — still has retries left |
| `manual_intervention_required` | one auto-retry exhausted (Story 7.7 AC2) |

The two indexes are partial (`WHERE status IN (...)`) so they cover
only the rows the worker actively scans on each tick; success and
manual_intervention_required rows are NOT indexed and remain queryable
via full-table scan when an admin debugs a failure (NFR42).

`downgrade()` raises `RuntimeError("forward-only migration — see NFR22")`,
matching migrations 010–015.

**ON DELETE CASCADE on recording_id**: when the user deletes a recording,
its delivery rows are removed. This contrasts with Sprint 4's
lost-and-found files (which survive deletion) — webhook deliveries are
ephemeral attempt records, not the underlying transcription artifact, so
losing them with the recording is the right call.

**ON DELETE SET NULL on profile_id**: profile deletion does NOT
cascade — historical attempts retain `profile_id=NULL` for traceability.

### 2.3 The `webhook_deliveries_repository` module

```python
# server/backend/database/webhook_deliveries_repository.py — NEW
"""Webhook delivery row persistence (Issue #104, Story 7.1)."""

from __future__ import annotations
import json, sqlite3
from collections.abc import Mapping
from typing import Any
from server.database.database import get_connection

VALID_STATUSES = frozenset({
    "pending", "in_flight", "success",
    "failed", "manual_intervention_required",
})

class InvalidWebhookStatusError(ValueError): ...

def create_pending(recording_id: int, profile_id: int | None,
                   payload: Mapping[str, Any]) -> int:
    """INSERT with status='pending' + payload_json. Commits. Returns row id."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO webhook_deliveries "
            "(recording_id, profile_id, status, payload_json) "
            "VALUES (?, ?, 'pending', ?)",
            (recording_id, profile_id, body),
        )
        conn.commit()
        return cur.lastrowid

def mark_in_flight(row_id: int) -> None: ...
def mark_success(row_id: int) -> None: ...
def mark_failed(row_id: int, error: str) -> None:
    """UPDATE status='failed', attempt_count++, last_error=?, last_attempted_at=NOW. Commits."""

def mark_manual_intervention(row_id: int, error: str) -> None: ...

def list_pending() -> list[sqlite3.Row]:
    """Worker query — every row in 'pending' or 'in_flight' (recovers in_flight on restart)."""

def get_latest_for_recording(recording_id: int) -> sqlite3.Row | None:
    """Most recent attempt — used by the retry endpoint to check 'success' for idempotency."""

def cleanup_older_than(days: int) -> int:
    """Delete success / manual_intervention_required rows older than N days. Returns deleted count.
    Does NOT delete pending / in_flight / failed (still actionable / queryable)."""
```

All writes commit before returning (Persist-Before-Deliver applies
to status transitions too — same discipline as
`auto_action_repository`).

### 2.4 URL allowlist validation (Story 7.2)

```python
# server/backend/core/webhook_url_validation.py — NEW
"""URL allowlist for outbound webhook delivery (Story 7.2 / FR44 / R-EL28)."""

from __future__ import annotations
import ipaddress, socket
from urllib.parse import urlparse
from typing import Literal


class WebhookUrlValidationError(ValueError):
    def __init__(self, code: Literal["scheme_not_allowed", "private_ip_blocked",
                                     "invalid_url", "dns_failure"],
                 detail: dict | None = None) -> None:
        self.code = code
        self.detail = detail or {}
        super().__init__(f"{code}: {detail}")


_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),       # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),      # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),     # IPv6 link-local
)


def validate_webhook_url(url: str, *, allow_localhost_http: bool = True) -> None:
    """Reject URLs that are not HTTPS or that resolve to private/loopback IPs.

    Raises WebhookUrlValidationError on any failure. Returns None on success.

    Called at TWO sites (TOCTOU-safe per AC3):
      1. Profile save (writes the URL to private_field_refs)
      2. WebhookWorker before each HTTP fire (re-resolution catches DNS-rebinding)
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise WebhookUrlValidationError("invalid_url", {"reason": str(exc)}) from exc

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise WebhookUrlValidationError("invalid_url", {"reason": "missing host"})

    # Scheme allowlist (FR44 / R-EL25 / NFR10)
    if scheme == "https":
        pass
    elif scheme == "http" and allow_localhost_http and host == "localhost":
        # Special-case literal 'localhost' for local development.
        # Skip the IP-resolution step since 127.0.0.1 would normally reject.
        return
    else:
        raise WebhookUrlValidationError(
            "scheme_not_allowed",
            {"allowed": ["https", "http (localhost only)"], "received": scheme},
        )

    # IP allowlist (FR44 / R-EL28 / NFR9). Resolves ALL records (A + AAAA + multi-homed)
    # — DNS rebinding can put one private record alongside a public one.
    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebhookUrlValidationError("dns_failure", {"reason": str(exc)}) from exc

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue  # not an address literal (shouldn't happen from getaddrinfo)
        for net in _PRIVATE_NETS:
            if ip.version == net.version and ip in net:
                raise WebhookUrlValidationError(
                    "private_ip_blocked",
                    {"ip": str(ip), "matched_range": str(net)},
                )
```

The validator is used at profile save (returns 400 with the error
dict as `detail`) AND inside `WebhookWorker.deliver` immediately
before the HTTP call. The two enforcement points satisfy AC3's
TOCTOU requirement.

### 2.5 The `WebhookWorker` lifecycle (Story 7.3)

```python
# server/backend/services/webhook_worker.py — NEW
"""WebhookWorker — singleton background dispatcher for webhook_deliveries.

Lifecycle:
  - start(): spawn the asyncio task that drains the pending queue
  - stop(grace=30.0): cancel the task; drain in-flight; revert un-fired
                      'in_flight' rows back to 'pending' so next-start picks
                      up cleanly (NFR24a / Story 7.3 AC5).

Single-instance per process — no fan-out across pods because the
deployment is single-container Docker. If the deployment ever
fans out, an advisory lock or claim_token column would prevent
two workers from picking up the same row; we explicitly accept
single-process scope.
"""

from __future__ import annotations
import asyncio, logging, time
from typing import Any
from server.database import webhook_deliveries_repository as wdr
from server.core.webhook_url_validation import (
    WebhookUrlValidationError,
    validate_webhook_url,
)

logger = logging.getLogger(__name__)

# Auto-retry budget (Story 7.7 AC2 — mirrors Story 6.11 escalation policy):
#   First failure → fresh row inserted with status='pending' after a 30s
#   delay (this lets the worker pick it up via the normal sweep path).
#   Second consecutive failure on the SAME recording → that row's status
#   flips to 'manual_intervention_required' instead of being re-queued.
MAX_AUTO_RETRIES = 1
AUTO_RETRY_DELAY_S = 30.0

# Worker tick interval — how often the queue is drained when there is
# no incoming work (lower bound on latency).
DEFAULT_POLL_INTERVAL_S = 5.0


class WebhookWorker:
    def __init__(self, *, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S) -> None:
        self._poll_interval = poll_interval_s
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()  # producer.notify_new_delivery() sets this

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._task = asyncio.create_task(self._run())
        logger.info("WebhookWorker started (poll=%.1fs)", self._poll_interval)

    async def stop(self, grace_s: float = 30.0) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._wake_event.set()  # break out of the wait
        try:
            await asyncio.wait_for(self._task, timeout=grace_s)
        except asyncio.TimeoutError:
            logger.warning("WebhookWorker stop timed out (%.1fs); cancelling", grace_s)
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("WebhookWorker task cancelled after timeout")
        finally:
            self._task = None
            # Sweep any 'in_flight' rows back to 'pending' so the next
            # start picks them up (Story 7.3 AC5 — never silently lost).
            try:
                wdr.requeue_in_flight_to_pending()
            except Exception:
                logger.exception("requeue_in_flight_to_pending failed during stop")

    def notify_new_delivery(self) -> None:
        """Producer hook — coordinator/retry endpoint calls this after INSERT."""
        self._wake_event.set()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("WebhookWorker tick failed; will retry next interval")
            try:
                # Wake on either: timeout (poll interval) or producer notify.
                await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_interval)
                self._wake_event.clear()
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                logger.debug("WebhookWorker run cancelled (shutdown)")
                return

    async def _tick(self) -> None:
        rows = await asyncio.to_thread(wdr.list_pending)
        for row in rows:
            if self._stop_event.is_set():
                return
            await self._deliver_one(row)

    async def _deliver_one(self, row: Any) -> None:
        """Deliver a single row. Persist-Before-Deliver:
           1. UPDATE status='in_flight' (committed)
           2. issue HTTP via httpx
           3. UPDATE status='success' or 'failed'/'manual_intervention_required'
        """
        # Implementation details in Story 7.4 / 7.5 commits.

# Module-level singleton, instantiated in lifespan(). Tests can construct
# their own instance and call start/stop directly.
_instance: WebhookWorker | None = None

def get_worker() -> WebhookWorker:
    global _instance
    if _instance is None:
        _instance = WebhookWorker()
    return _instance
```

**Lifespan wiring** in `api/main.py` (mirror of `auto_action_sweeper`):

```python
# api/main.py — lifespan, after deferred-export sweep block
webhook_config = config.config.get("webhook_deliveries", {})
_webhook_worker_enabled = webhook_config.get("enabled", True)

if _webhook_worker_enabled:
    from server.services.webhook_worker import get_worker
    _webhook_worker = get_worker()
    await _webhook_worker.start()
    _log_time("webhook worker started")

# ... yield ...

if _webhook_worker is not None:
    await _webhook_worker.stop(grace_s=30.0)
```

The `+5 lines` budget Story 7.3 AC2 mentions is a *guideline*, not a
hard cap; the actual diff is `import + start() + stop()` plus the
config-flag block. The intent (minimal `main.py` churn) is preserved —
all complexity lives in `services/webhook_worker.py`.

### 2.6 The HTTP delivery contract (Story 7.4)

```python
# inside _deliver_one — webhook_worker.py

import httpx

async def _http_post_with_contract(
    url: str, payload: dict, headers: dict | None = None
) -> tuple[int, str | None]:
    """POST with the security contract:
       - 10s total timeout (NFR5)
       - follow_redirects=False (NFR11 / R-EL26)
       - Accept-Encoding: identity (NFR12 — no decompression)
       - body bytes discarded; only status_code matters (FR45 AC4)

    Returns (status_code, error_or_none). Never raises for HTTP errors —
    raises ONLY for transport / timeout failures (which the caller maps
    to error='timeout' / error='transport: <repr>').
    """
    final_headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    if headers:
        final_headers.update(headers)
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(url, json=payload, headers=final_headers)
        # Discard body without inflation. Even though httpx may have read
        # `response.content` to a bytes attribute, we don't decode it —
        # the body is opaque per FR45 AC4.
        return (response.status_code, None)


# Inside _deliver_one:
try:
    validate_webhook_url(url)  # TOCTOU re-check (Story 7.2 AC3)
except WebhookUrlValidationError as exc:
    wdr.mark_failed(row_id, f"url_validation_failed: {exc.code}")
    return

try:
    status_code, _ = await _http_post_with_contract(url, payload, headers=auth_headers)
except httpx.TimeoutException:
    self._handle_failure(row_id, recording_id, "timeout")
    return
except httpx.RequestError as exc:  # connect refused, DNS, etc.
    self._handle_failure(row_id, recording_id, f"transport: {type(exc).__name__}")
    return

if 200 <= status_code < 300:
    wdr.mark_success(row_id)
else:
    self._handle_failure(row_id, recording_id, f"http_{status_code}")
```

Where `_handle_failure` implements the two-strikes escalation:

```python
def _handle_failure(self, row_id: int, recording_id: int, error: str) -> None:
    """Story 7.7 AC2 escalation: count consecutive failed rows for this
    recording (across rows, since each retry inserts a new row).
    """
    consecutive = wdr.count_consecutive_recent_failures(recording_id)
    if consecutive >= MAX_AUTO_RETRIES:
        wdr.mark_manual_intervention(row_id, error)
        logger.warning(
            "webhook escalated to manual_intervention_required: "
            "recording=%d consecutive_failures=%d error=%s",
            recording_id, consecutive + 1, error,
        )
        return
    wdr.mark_failed(row_id, error)
    asyncio.create_task(_schedule_retry(recording_id, AUTO_RETRY_DELAY_S))


async def _schedule_retry(recording_id: int, delay_s: float) -> None:
    """Wait `delay_s` then re-queue. Cancel-safe: if cancelled, the row
    stays at 'failed' and the user can manual-retry via the badge."""
    try:
        await asyncio.sleep(delay_s)
    except asyncio.CancelledError:
        return
    # Re-fetch the original payload + URL from the failed row and
    # INSERT a fresh pending row.
    wdr.requeue_failed_row(recording_id)
    get_worker().notify_new_delivery()
```

### 2.7 Payload v1 (Story 7.6)

```python
# server/backend/core/webhook_payload.py — NEW
"""Webhook payload construction (Story 7.6 / FR46 / R-EL31)."""

from __future__ import annotations
from datetime import UTC, datetime
from typing import Any

PAYLOAD_VERSION = "1.0"
LARGE_PAYLOAD_WARN_BYTES = 1_048_576  # 1 MB

import logging
logger = logging.getLogger(__name__)


def build_payload(
    *,
    recording_id: int,
    profile_id: int | None,
    summary_present: bool,
    transcript_text: str | None = None,
) -> dict[str, Any]:
    """Construct the metadata-default payload, optionally with transcript text.

    The receiver is expected to know the server base URL out-of-band
    (it configured the webhook); URLs in the body are server-relative.
    """
    body: dict[str, Any] = {
        "event": "transcription.completed",
        "recording_id": recording_id,
        "profile_id": profile_id,
        "transcript_url": f"/api/notebook/recordings/{recording_id}/segments",
        "summary_url": (
            f"/api/notebook/recordings/{recording_id}" if summary_present else None
        ),
        "payload_version": PAYLOAD_VERSION,
        "timestamp_iso": datetime.now(UTC).isoformat(),
        # Forward-compat envelope: the doc says the contract supports
        # back-compat for 2 minor releases. Receivers branch on the
        # `payload_version` string field above.
        "webhook_version": 1,
    }
    if transcript_text is not None:
        body["transcript_text"] = transcript_text
        # Heuristic estimate via UTF-8 byte length — accurate enough
        # for the 1MB advisory threshold.
        size_bytes = len(transcript_text.encode("utf-8"))
        if size_bytes > LARGE_PAYLOAD_WARN_BYTES:
            logger.warning(
                "Large webhook payload — recording_id=%d transcript_size_bytes=%d "
                "(consider URL fetch instead of inline transcript_text)",
                recording_id, size_bytes,
            )
    return body
```

The `webhook_version: 1` integer field at the top level is deliberate
forward-compat insurance per the prompt's gotcha #6 — it sits alongside
the AC1-mandated `payload_version: "1.0"` string field. Future schema
changes can land as `payload_version: "1.1"` / `webhook_version: 1` (no
breaking change) or as `webhook_version: 2` (breaking — receivers must
opt in).

### 2.8 Profile schema additions (Story 7.2)

`ProfilePublicFields` extension:

```python
# api/routes/profiles.py — additions to ProfilePublicFields
class ProfilePublicFields(BaseModel):
    # ... existing fields ...
    webhook_url: str = ""
    webhook_include_transcript_text: bool = False
    # webhook_auth_header value is private — stored via private_field_refs
```

A new validator in `profiles.py` runs URL validation at SAVE time:

```python
def _validate_webhook_url(public_fields: Any) -> None:
    if public_fields is None:
        return
    url = (
        public_fields.webhook_url if hasattr(public_fields, "webhook_url") else ""
    )
    if not url:
        return
    from server.core.webhook_url_validation import (
        WebhookUrlValidationError, validate_webhook_url,
    )
    try:
        validate_webhook_url(url)
    except WebhookUrlValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": exc.code, **exc.detail},
        )
```

Called from `create_profile` and `update_profile` immediately after
`_validate_template`.

### 2.9 Coordinator integration (Story 7.5 producer side)

`auto_action_coordinator.trigger_auto_actions` gains a third branch:

```python
# core/auto_action_coordinator.py — addition
if public.get("webhook_url"):
    tasks.append(asyncio.create_task(_run_webhook_dispatch(recording_id, public)))


async def _run_webhook_dispatch(
    recording_id: int, public: Mapping[str, Any]
) -> None:
    """Insert a 'pending' row into webhook_deliveries; poke the worker.

    Persist-Before-Deliver: the row is durable BEFORE the worker tries
    the HTTP call. This function does NOT issue HTTP — the worker does.
    """
    from server.core.webhook_payload import build_payload
    from server.database import webhook_deliveries_repository as wdr
    from server.database.database import get_recording
    from server.services.webhook_worker import get_worker

    recording = get_recording(recording_id) or {}
    profile_id = recording.get("profile_id")
    summary_present = bool(recording.get("summary"))

    transcript_text: str | None = None
    if public.get("webhook_include_transcript_text"):
        # Build the full plaintext exactly as the export path does
        # (alias-substituted so receivers see canonical names).
        from server.core.alias_substitution import apply_aliases
        from server.core.plaintext_export import stream_plaintext
        from server.database.alias_repository import list_aliases
        from server.database.database import get_segments

        segments = get_segments(recording_id)
        aliases = {a["speaker_id"]: a["alias_name"] for a in list_aliases(recording_id)}
        transcript_text = "".join(stream_plaintext(recording, apply_aliases(segments, aliases)))

    payload = build_payload(
        recording_id=recording_id,
        profile_id=profile_id,
        summary_present=summary_present,
        transcript_text=transcript_text,
    )

    try:
        wdr.create_pending(recording_id, profile_id, payload)
    except Exception:
        logger.exception("webhook create_pending failed for recording %d", recording_id)
        return
    get_worker().notify_new_delivery()
```

### 2.10 Retention cleanup (Story 7.7 AC3)

Mirrors `audio_cleanup.periodic_cleanup`:

```python
# server/backend/database/webhook_cleanup.py — NEW
import asyncio, logging
from server.database import webhook_deliveries_repository as wdr

logger = logging.getLogger(__name__)


async def periodic_webhook_cleanup(
    retention_days: int, interval_hours: int = 24
) -> None:
    """Run cleanup_older_than on a repeating schedule. Mirrors audio_cleanup."""
    try:
        deleted = await asyncio.to_thread(wdr.cleanup_older_than, retention_days)
        logger.info("webhook cleanup: deleted %d row(s) older than %dd", deleted, retention_days)
    except Exception:
        logger.exception("Initial webhook cleanup failed — periodic retries will continue")

    if interval_hours <= 0:
        return
    interval_s = interval_hours * 3600
    while True:
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            logger.info("Periodic webhook cleanup cancelled (shutdown)")
            return
        try:
            deleted = await asyncio.to_thread(wdr.cleanup_older_than, retention_days)
            logger.info("webhook cleanup: deleted %d row(s)", deleted)
        except Exception:
            logger.exception("Periodic webhook cleanup failed — will retry next interval")
```

Wired in `lifespan` next to the existing `audio_cleanup.periodic_cleanup`
schedule. Gated on `webhook_deliveries.retention_enabled` (default true)
and `webhook_deliveries.retention_days` (default 30) in `config.yaml`.

### 2.11 Retry endpoint integration (Story 7.7 AC1)

The Sprint 4 retry endpoint at `notebook.py:1692` extends:

```python
class AutoActionRetryRequest(BaseModel):
    action_type: Literal["auto_summary", "auto_export", "webhook"]


@router.post("/recordings/{recording_id}/auto-actions/retry")
async def retry_auto_action(...):
    if payload.action_type == "webhook":
        # Use the latest delivery row to enforce idempotency.
        from server.database import webhook_deliveries_repository as wdr
        latest = wdr.get_latest_for_recording(recording_id)
        if latest is not None and latest["status"] == "success":
            response.status_code = 200
            return AutoActionRetryResponse(
                recording_id=recording_id, action_type="webhook",
                status="already_complete",
            )
        if latest is not None and latest["status"] in ("pending", "in_flight"):
            response.status_code = 200
            return AutoActionRetryResponse(
                recording_id=recording_id, action_type="webhook",
                status="already_in_progress",
            )
        # Re-queue: rebuild payload from the original profile snapshot
        # (Sprint 4 saved this on the recording row already).
        from server.database.auto_action_repository import get_profile_snapshot
        from server.core.auto_action_coordinator import _run_webhook_dispatch
        snapshot = get_profile_snapshot(recording_id) or {}
        public = snapshot.get("public_fields") or {}
        if not public.get("webhook_url"):
            raise HTTPException(
                status_code=400,
                detail={"error": "no_webhook_configured"},
            )
        asyncio.create_task(_run_webhook_dispatch(recording_id, public))
        response.status_code = 202
        return AutoActionRetryResponse(
            recording_id=recording_id, action_type="webhook",
            status="retry_initiated",
        )
    # ... existing auto_summary / auto_export branches unchanged ...
```

### 2.12 Frontend status surfacing (Story 7.7 AC1)

Three changes to the dashboard:

1. **`AutoActionStatusBadge`** — extend `AutoActionType` union to
   include `"webhook"`. Add `webhook` row to `ACTION_LABEL`. Status
   mappings already cover the strings (`failed`, `manual_intervention_required`,
   `pending`, `in_flight`, `success`).

2. **`AudioNoteModal`** — read `recording.webhook_status` (a virtual
   column derived server-side from the latest `webhook_deliveries` row
   for that recording, included in the GET response) and render a third
   badge if present.

3. **`useAutoActionRetry`** — already accepts an action_type; just pass
   `"webhook"` from the badge's onRetry handler.

The "virtual column" (`webhook_status`) comes from a JOIN added in
`get_recording`:

```python
# database.py — get_recording extension
SELECT recordings.*,
       (SELECT status FROM webhook_deliveries
        WHERE recording_id = recordings.id
        ORDER BY id DESC LIMIT 1) AS webhook_status,
       (SELECT last_error FROM webhook_deliveries
        WHERE recording_id = recordings.id
        ORDER BY id DESC LIMIT 1) AS webhook_error
FROM recordings WHERE id = ?
```

This keeps the frontend payload shape uniform (no separate API call).

---

## 3. Per-story design

### Story 7.1 — `webhook_deliveries` table migration

**Migration 016** as designed in §2.2 + repository module as designed in §2.3.

**Tests (`tests/test_webhook_deliveries_migration.py`):**
- `test_table_exists_after_migration` — assert PRAGMA table_info shows all 9 columns.
- `test_status_check_constraint` — INSERT with status='bogus' raises IntegrityError.
- `test_indexes_present` — assert idx_webhook_deliveries_status + idx_webhook_deliveries_recording exist.
- `test_cascade_on_recording_delete` — INSERT row, DELETE recording, assert row gone.
- `test_set_null_on_profile_delete` — INSERT row with profile_id, DELETE profile, assert row.profile_id IS NULL.
- `test_downgrade_raises` — assert RuntimeError raised on downgrade attempt.

**Tests (`tests/test_webhook_deliveries_repository.py`):**
- `test_create_pending_returns_id_and_commits` — assert row visible in fresh connection.
- `test_mark_in_flight_updates_status` — happy path.
- `test_mark_success_updates_status_and_attempted_at` — happy path.
- `test_mark_failed_increments_attempt_count` — first call: count=1, second: count=2.
- `test_list_pending_returns_only_pending_and_in_flight` — exclude success / failed / manual.
- `test_get_latest_for_recording_returns_newest` — multiple rows, assert order.
- `test_cleanup_older_than_skips_pending_and_failed` — only success + manual deleted; NEVER pending / in_flight / failed.
- `test_cleanup_older_than_uses_created_at_not_attempted_at` — semantic clarity test.

### Story 7.2 — URL allowlist validation

`webhook_url_validation.py` as designed in §2.4 + ProfilePublicFields extension in §2.8.

**Tests (`tests/test_webhook_url_validation.py`):**
- `test_https_public_url_accepted` — happy path (uses `private_ip_resolver.add("api.example.com", "203.0.113.1")`).
- `test_http_localhost_accepted` — `http://localhost:5000/foo` passes.
- `test_http_non_localhost_rejected` — `http://api.example.com/foo` raises `scheme_not_allowed`.
- `test_ftp_rejected` — `ftp://example.com` raises `scheme_not_allowed`.
- `test_rfc1918_blocked` — `https://internal.local` resolved to `10.0.0.5` raises `private_ip_blocked` (uses `private_ip_resolver`).
- `test_127_blocked` — `https://api.example.com` resolved to `127.0.0.5` raises `private_ip_blocked`.
- `test_169_254_blocked` — AWS-metadata IP raises `private_ip_blocked`.
- `test_ipv6_loopback_blocked` — `https://[::1]/foo` raises `private_ip_blocked`.
- `test_ipv6_ula_blocked` — `fc00::1` raises `private_ip_blocked`.
- `test_dns_failure_raises` — unresolvable hostname raises `dns_failure`.
- `test_multi_record_one_private_blocks` — DNS returns `[203.0.113.1, 10.0.0.5]`; rejected because ANY record is private.

**Tests (`tests/test_profiles_webhook_url_validation.py`):**
- `test_create_profile_with_https_url_succeeds` — POST /api/profiles with valid URL → 200.
- `test_create_profile_with_private_ip_returns_400` — POST with `https://internal.local` (private_ip_resolver) → 400 + body `{"error": "private_ip_blocked", ...}`.
- `test_create_profile_with_ftp_url_returns_400` — body `{"error": "scheme_not_allowed", ...}`.
- `test_create_profile_with_no_webhook_url_succeeds` — empty string is valid (toggle-off).

### Story 7.3 — `WebhookWorker` skeleton + lifespan

`services/webhook_worker.py` as designed in §2.5 + `api/main.py` lifespan additions.

**Tests (`tests/test_webhook_worker_lifecycle.py`):**
- `test_worker_starts_and_stops_cleanly` — start, then stop within grace, no warnings logged.
- `test_worker_drains_pending_rows` — INSERT 3 pending rows, start worker, assert all marked success (uses `webhook_mock_receiver` returning 200).
- `test_worker_picks_up_in_flight_on_restart` — INSERT row at status='in_flight' (simulates prior crash), start, assert it's drained.
- `test_worker_requeues_in_flight_on_stop` — start worker, manually flip a row to in_flight, stop, assert row reverted to pending.
- `test_notify_new_delivery_wakes_loop` — start with poll=60s, INSERT row, call notify, assert row drained within 1s.
- `test_cancel_safe_shutdown` — start worker, cancel its task directly, assert no exception leaks.

**Tests (`tests/test_webhook_worker_memory_budget.py`):**
- `test_worker_memory_budget_under_load` — gated on `WEBHOOK_MEMORY_BUDGET=1` env var (skipped in normal CI). Runs 60s with 10 webhook_mock_receiver fires/sec at 200ms response delay; asserts p95 RSS-delta ≤ 50 MB and slope ≈ 0.

### Story 7.4 — Delivery contract

`_http_post_with_contract` helper as designed in §2.6.

**Tests (`tests/test_webhook_delivery_contract.py`):**
- `test_timeout_at_10s` — `webhook_mock_receiver.set_response(200, delay_seconds=15)`; assert `httpx.TimeoutException` raised within 11s; row marked `failed` with `last_error="timeout"`. Test budget: ~12s.
- `test_no_redirect_following` — `webhook_mock_receiver.set_redirect("https://elsewhere.example.com")`; assert worker did NOT issue follow-up request (controller only saw 1 request); row marked `failed` with `last_error="http_302"`.
- `test_no_decompression` — `webhook_mock_receiver.set_response(200, body=<gzip-encoded bytes>, headers=Content-Encoding: gzip)`; assert worker did NOT inflate body; status_code branch chose success.
- `test_status_code_2xx_success` — 200, 201, 204 all → success.
- `test_status_code_3xx_failure` — 301, 302, 304, 308 all → failed.
- `test_status_code_4xx_failure` — 400, 401, 403, 404 all → failed (no special-case auth retries).
- `test_status_code_5xx_failure` — 500, 502, 503 all → failed (still escalates per Story 7.7).
- `test_accept_encoding_identity_header_sent` — assert request headers include `Accept-Encoding: identity`.

### Story 7.5 — Persist-Before-Deliver

Coordinator producer in §2.9 + worker tick + Persist-Before-Deliver discipline in §2.1.

**Tests (`tests/test_webhook_persist_before_deliver.py`):**
- `test_pending_row_inserted_before_http_fire` — monkeypatch `_http_post_with_contract` to assert the row exists at `pending` BEFORE it's called. Use a recorded event log (matches Sprint 4's PBD matrix shape).
- `test_in_flight_transition_committed_before_http_fire` — monkeypatch as above; assert row visible at `in_flight` (in a separate connection) before HTTP call.
- `test_pending_recovered_on_restart` — INSERT pending row, do NOT start worker, then start worker, assert row drained.
- `test_in_flight_recovered_on_restart` — same with in_flight.
- `test_db_commit_failure_leaves_row_pending` — monkeypatch `mark_in_flight` to raise; assert HTTP NOT issued, row stays pending.
- `test_payload_json_persisted_for_diagnostic` — INSERT, fetch row, JSON-decode payload_json, assert all fields present.

### Story 7.6 — Payload v1

`webhook_payload.py` as designed in §2.7.

**Tests (`tests/test_webhook_payload.py`):**
- `test_default_metadata_only` — `build_payload(transcript_text=None)`; assert exact key set (no `transcript_text`).
- `test_opt_in_includes_transcript_text` — `transcript_text="hello"`; assert key present + value.
- `test_payload_version_is_1_0_string` — assert `payload_version == "1.0"`.
- `test_webhook_version_is_1_int` — assert `webhook_version == 1`.
- `test_summary_url_is_null_when_summary_absent` — `summary_present=False`; assert `summary_url is None`.
- `test_timestamp_iso_utc` — assert ends with `+00:00` or `Z`.
- `test_large_transcript_warns` — transcript > 1MB; assert warning logged.

### Story 7.7 — Failed delivery surfacing + retention

Retention task in §2.10 + retry endpoint extension in §2.11 + frontend
extensions in §2.12.

**Tests (backend, `tests/test_webhook_retention.py`):**
- `test_cleanup_deletes_success_older_than_n_days` — INSERT success row with created_at = NOW - 31d; cleanup_older_than(30); assert deleted.
- `test_cleanup_skips_recent_success` — INSERT success row at NOW - 5d; cleanup_older_than(30); assert NOT deleted.
- `test_cleanup_skips_pending_and_failed` — even if old; pending/in_flight/failed always retained for action / queryability.
- `test_periodic_task_first_run_immediate_subsequent_periodic` — same shape as audio_cleanup test.
- `test_periodic_task_cancel_safe` — task cancelled mid-sleep → no exception.

**Tests (backend, `tests/test_webhook_retry_endpoint.py`):**
- `test_retry_webhook_after_failure_returns_202` — manually mark row failed; POST retry; assert 202 + retry_initiated.
- `test_retry_webhook_after_success_returns_already_complete` — mark row success; POST retry; assert 200 + already_complete + NO new INSERT.
- `test_retry_webhook_no_url_configured_returns_400` — profile has no webhook_url; POST retry; assert 400 + `no_webhook_configured`.
- `test_retry_webhook_during_in_flight_returns_already_in_progress` — manually mark row in_flight; POST retry; assert 200 + already_in_progress.

**Tests (backend, `tests/test_webhook_escalation.py`):**
- `test_two_consecutive_failures_escalate_to_manual` — fail twice consecutively; assert second row's status = manual_intervention_required.
- `test_intervening_success_resets_consecutive_count` — fail, success, fail; assert NOT escalated (one auto-retry available again).

**Tests (frontend, Vitest, `dashboard/components/recording/__tests__/AutoActionStatusBadge.webhook.test.tsx`):**
- `test_webhook_failed_renders_retry` — props with action_type='webhook', status='failed'; assert ⟳ Retry button visible.
- `test_webhook_manual_intervention_renders_message` — props with status='manual_intervention_required'; assert "Manual intervention required" text.

**Tests (frontend, `dashboard/components/views/__tests__/AudioNoteModal.webhook.test.tsx`):**
- `test_webhook_status_badge_rendered_when_present` — recording with `webhook_status='failed'`; assert badge visible.
- `test_no_webhook_badge_when_status_null` — recording with `webhook_status=null`; assert no badge.

---

## 4. Risks and Stop-Conditions

| Risk | Mitigation | Stop-condition |
|---|---|---|
| SSRF bypass via URL with public DNS → private IP rebind | TOCTOU re-validation inside worker before HTTP fire (§2.4 enforced at TWO sites) | If a test demonstrates rebinding attack succeeds, STOP — escalate before merge |
| Retry storm (e.g. flapping endpoint) | One auto-retry then manual; sweeper does NOT re-fire manual rows | If retry counts grow unboundedly in logs, profile + add per-recording rate limit |
| Worker memory leak under sustained load | Memory-budget test gated behind `WEBHOOK_MEMORY_BUDGET=1` | If p95 > 50 MB or slope > 0.1 MB/s, STOP — investigate httpx connection pooling |
| Duplicate webhook fire after crash mid-`in_flight` | Documented as accepted trade (durability beats at-most-once); retention DB has the trail | If receivers complain about duplicates, add an `Idempotency-Key` request header keyed on `webhook_deliveries.id` |
| Sprint diff exceeds ~2500 LOC | LOC budget per commit (§7) totals ~1450 prod + ~1050 tests = ~2500 | If commits A–F together exceed 2200 LOC, STOP and split |
| Test runner accidentally hits real network | `flake8-tidy-imports.banned-api` blocks `httpx.AsyncClient` in tests; fixture is the only path | If a test imports httpx directly, ruff fails the build |
| Payload v1 contract drift | `test_default_metadata_only` is a snapshot test — any unintended addition breaks it | If a future PR mutates the payload, the test catches it |

---

## 5. Recording-deletion + cascade matrix update

| User action | DB rows | Notes |
|---|---|---|
| Click Delete (recording) | recording row + ALL webhook_deliveries rows for that recording (CASCADE) | Failure history is lost with the recording — accepted, since the recording itself is the receiver's primary key |
| Delete profile | profiles row removed; webhook_deliveries.profile_id → NULL (SET NULL) | Historical attempts retain traceability via NULL profile_id |
| Cleanup task | success / manual_intervention_required rows older than N days deleted | pending / in_flight / failed always retained |

---

## 6. Out-of-sprint observations (record only)

- **Webhook authentication header rotation** — when the user updates the
  auth header, in-flight `pending` rows still carry the OLD header in
  their `payload_json`. Sprint 5 does NOT re-fetch the header at delivery
  time; future work could add a `auth_header_ref` column.
- **Webhook signing (HMAC of body)** — out of scope; receivers that need
  signature verification should be implemented by Sprint 6+.
- **Per-recording webhook URL override** — current design uses the profile's
  webhook URL exclusively. Per-recording overrides could be supported
  via a `recordings.webhook_url_override` column in a future sprint.
- **Webhook delivery telemetry / metrics** — local Prometheus-style logs
  are OK to add later; CLAUDE.md "no outbound telemetry" still applies.
- **Configurable retry budget** — currently hard-coded to 1 auto-retry
  (matches Sprint 4 pattern). A per-profile `webhook_retry_max` could be
  added later.

---

## 7. Commit plan recap (with LOC estimates)

| Commit | Stories | Files | Est. LOC | Notes |
|---|---|---|---|---|
| A | 7.1 | migration 016, webhook_deliveries_repository.py, 2 test files | ~400 | Foundation table + repo |
| B | 7.2 | webhook_url_validation.py, profiles.py validator hook, ProfilePublicFields extension, 2 test files | ~350 | Security baseline |
| C | 7.3 | services/webhook_worker.py (skeleton: start/stop/lifecycle), main.py lifespan, config.yaml block, 1 test file | ~300 | Worker + lifespan |
| D | 7.4 | webhook_worker.py (_http_post_with_contract, _deliver_one), 1 test file | ~250 | Delivery contract |
| E | 7.5 | auto_action_coordinator._run_webhook_dispatch, webhook_worker (PBD discipline), 1 test file | ~200 | Producer + PBD |
| F | 7.6 | webhook_payload.py + wired into _run_webhook_dispatch, 1 test file | ~150 | Payload v1 |
| G | 7.7 | webhook_cleanup.py + lifespan, retry endpoint extension, AutoActionStatusBadge / AudioNoteModal extensions, 4 test files | ~450 | Failure surfacing + retention |
| Final | mark 7 stories DONE in epics.md | epics.md | ~30 | Bookkeeping |

**Total ~2100 LOC + tests** — within the 2500 LOC ceiling.

---

## 8. Dependency order recap

```
   A (7.1 migration + repo)
   │
   ▼
   B (7.2 URL validator + profile schema)
   │
   ▼
   C (7.3 worker skeleton + lifespan)
   │
   ▼
   D (7.4 delivery contract)
   │
   ▼
   E (7.5 PBD producer + worker tick)
   │
   ▼
   F (7.6 payload v1)
   │
   ▼
   G (7.7 retention + retry + frontend)
```

Linear order A → B → C → D → E → F → G satisfies all import-time and
consumer-pattern dependencies. Each commit lands as its own logical unit;
the sprint ships as one branch (`gh-104-sprint-5`) and merges to
`gh-104-prd` like Sprints 1–4.
