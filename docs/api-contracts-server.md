# TranscriptionSuite — API Contracts (Server)

> Generated: 2026-06-11 | v1.3.6 | Base URL: `http(s)://host:9786`

## Auth Legend

- **none** — public route (always reachable; see `PUBLIC_ROUTES`/`PUBLIC_PREFIXES` in `main.py`)
- **user** — requires a valid token in TLS mode (enforced globally by `AuthenticationMiddleware`); open in local mode
- **admin** — handler calls `require_admin()`; 403 if not admin. In local mode, loopback/Docker-gateway hosts are treated as admin.

> **Local-mode nuance:** when `TLS_ENABLED=false` (default), `AuthenticationMiddleware` is not installed, so
> "user" routes are effectively open; "admin" routes still run `require_admin`, which loopback callers pass.
> In **TLS mode**, every non-public route needs a Bearer token (header) or `auth_token` cookie; the notebook
> `…/audio` and `…/export` routes additionally accept a `?token=` query param.

## Endpoint Summary

### Health & Status
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | none | Liveness probe (`{status, service}`) |
| GET | `/ready` | user | Readiness — 200 when model loaded/disabled or Live Mode active, else 503 |
| GET | `/api/status` | none | Detailed status: version, models, features, `ready`, `gpu_available`, `gpu_error` |

### Authentication (`/api/auth`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/auth/login` | none | Validate a token; returns `{name, is_admin, token_id}` |
| GET | `/api/auth/tokens` | admin | List tokens (partial hash only) |
| POST | `/api/auth/tokens` | admin | Create token (plaintext shown once) |
| DELETE | `/api/auth/tokens/{token_id}` | admin | Revoke token |

### Transcription (`/api/transcribe`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/transcribe/audio` | user | Full transcription (text + segments + words + optional diarization); supports `multitrack`, `profile_id`; persists before delivery |
| POST | `/api/transcribe/quick` | user | Fast text-only transcription (Record view) |
| POST | `/api/transcribe/cancel` | user | Cancel the active job |
| POST | `/api/transcribe/import` | user | Background transcribe (no DB/notebook); 202 + `job_id` + inline `dedup_matches`; supports `multitrack` |
| POST | `/api/transcribe/import/dedup-check` | user | **NEW** — look up prior jobs/recordings sharing an audio hash (no side effects) |
| GET | `/api/transcribe/result/{job_id}` | user | **NEW** — fetch saved result (200 done / 202 processing / 404 / 410 failed); marks delivered; ownership check |
| POST | `/api/transcribe/retry/{job_id}` | user | **NEW** — re-transcribe a failed job from preserved audio |
| GET | `/api/transcribe/recent` | user | **NEW** — up to 5 recently completed-but-undelivered jobs (post-restart recovery banner) |
| POST | `/api/transcribe/result/{job_id}/dismiss` | user | **NEW** — mark a result delivered without transferring payload |
| GET | `/api/transcribe/languages` | user | Supported languages for active backend, `auto_detect`, `supports_translation` |

### Audio Notebook (`/api/notebook`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/notebook/recordings` | user | List recordings (optional `start_date`/`end_date`) |
| GET | `/api/notebook/recordings/{id}` | user | Recording detail incl. segments, words, `webhook_status`/`webhook_error` |
| DELETE | `/api/notebook/recordings/{id}` | user | Delete recording (+ optional on-disk artifacts) |
| PUT/PATCH | `/api/notebook/recordings/{id}/summary` | user | Update summary (query / JSON body) |
| PATCH | `/api/notebook/recordings/{id}/transcript` | user | **NEW** — set/clear non-destructive `transcript_corrected` (find-replace persistence) |
| PATCH | `/api/notebook/recordings/{id}/title` | user | Update title |
| PATCH | `/api/notebook/recordings/{id}/date` | user | Update `recorded_at` |
| GET | `/api/notebook/recordings/{id}/diarization-review` | user | **NEW** — diarization-review lifecycle state |
| POST | `/api/notebook/recordings/{id}/diarization-review` | user | **NEW** — lifecycle trigger `open`/`complete` (409 on illegal transition) |
| GET | `/api/notebook/recordings/{id}/diarization-confidence` | user | **NEW** — per-turn confidence + `alternative_speakers` |
| GET | `/api/notebook/recordings/{id}/aliases` | user | **NEW** — list speaker aliases |
| PUT | `/api/notebook/recordings/{id}/aliases` | user | **NEW** — full-replace upsert of speaker aliases |
| GET | `/api/notebook/recordings/{id}/audio` | user (+`?token=`) | Stream audio with HTTP Range (206) |
| GET | `/api/notebook/recordings/{id}/transcription` | user | Transcription as segments-with-embedded-words |
| POST | `/api/notebook/transcribe/upload` | user | Upload + background transcribe + save to notebook; 202 + `job_id`; supports diarization, `profile_id` |
| GET | `/api/notebook/calendar` | user | Recordings grouped by day for a `year`/`month` |
| GET | `/api/notebook/timeslot` | user | Time-slot occupancy for `date`+`hour` |
| GET | `/api/notebook/recordings/{id}/export` | user (+`?token=`) | Export transcript: `txt`/`plaintext`/`srt`/`ass` (alias-substituted) |
| POST | `/api/notebook/recordings/{id}/reexport` | user | **NEW** — re-render plaintext export with a `profile_id` to its destination folder |
| POST | `/api/notebook/recordings/{id}/auto-actions/retry` | user | **NEW** — idempotent retry of `auto_summary`/`auto_export`/`webhook` |
| GET | `/api/notebook/backups` | user | List database backups |
| POST | `/api/notebook/backup` | user | Create a manual DB backup |
| POST | `/api/notebook/restore` | user | Restore DB from a named backup (safety-backup first) |

### Profiles (`/api/profiles`) — entire family NEW
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/profiles` | user | List profiles (sensitive keys scrubbed) |
| GET | `/api/profiles/{profile_id}` | user | Get one profile (404 if absent) |
| POST | `/api/profiles` | user | Create profile (201); validates schema_version, filename template, webhook URL (SSRF) |
| PUT | `/api/profiles/{profile_id}` | user | Update profile (exclude-unset; null clears) |
| DELETE | `/api/profiles/{profile_id}` | user | Delete profile (204 / 404) |

### Search (`/api/search`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/search/words` | user | FTS5 word search with timing + recording context |
| GET | `/api/search/recordings` | user | Search recordings containing a query |
| GET | `/api/search/` | user | Unified search (words + filename/title/summary), optional date range |

### LLM Integration (`/api/llm`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/llm/status` | user | Provider reachability + active model + `auto_title_enabled` |
| POST | `/api/llm/config/reload` | user | **NEW** — reload server config from disk (new LLM base URL) |
| GET | `/api/llm/models` | user | **NEW** — list provider models (`/v1/models`) |
| POST | `/api/llm/process` | user | Non-streaming LLM processing of transcription text |
| POST | `/api/llm/process/stream` | user | Streaming (SSE) LLM processing |
| POST | `/api/llm/summarize/{recording_id}` | user | Summarize recording (alias-aware; persists; 409 if in-flight) |
| POST | `/api/llm/summarize/{recording_id}/stream` | user | Streaming summarize (persist-on-complete) |
| GET | `/api/llm/models/available` | user | LM Studio v0 models (load state, quant, ctx len) |
| POST | `/api/llm/model/load` | user | Load a model into LM Studio (v1 REST) |
| POST | `/api/llm/model/unload` | user | Unload a model from LM Studio |
| GET | `/api/llm/models/loaded` | user | **NEW** — loaded models via `lms ps` |
| POST | `/api/llm/server/start` | user | Check LM Studio + load configured model |
| POST | `/api/llm/server/stop` | user | (No-op in Docker) stop LM Studio |
| GET | `/api/llm/conversations/{recording_id}` | user | **NEW** — list AI-chat conversations for a recording |
| POST | `/api/llm/conversations` | user | **NEW** — create a conversation |
| GET | `/api/llm/conversation/{conversation_id}` | user | **NEW** — get conversation + messages |
| PATCH | `/api/llm/conversation/{conversation_id}` | user | **NEW** — update title and/or model override |
| DELETE | `/api/llm/conversation/{conversation_id}` | user | **NEW** — delete a conversation |
| POST | `/api/llm/conversation/{conversation_id}/message` | user | **NEW** — add a manual message |
| DELETE | `/api/llm/conversation/{conversation_id}/messages-from/{message_id}` | user | **NEW** — truncate history from a message |
| POST | `/api/llm/conversation/{conversation_id}/generate-title` | user | **NEW** — LLM-generate a short title |
| POST | `/api/llm/chat` | user | **NEW** — multi-turn streaming chat over transcription (alias-aware) |

### Admin (`/api/admin`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/admin/status` | admin | Detailed model/transcriber/diarization status |
| PATCH | `/api/admin/diarization` | admin | Update diarization `parallel` setting |
| GET | `/api/admin/config/full` | admin | Full `config.yaml` as a tree (comments/types) |
| PATCH | `/api/admin/config` | admin | In-place config updates `{updates:{section.key:value}}` |
| POST | `/api/admin/webhook/test` | admin | Send a test webhook (legacy config or supplied url/secret) |
| POST | `/api/admin/models/load` | admin | Load a model (503 on missing backend dep) |
| WS | `/api/admin/models/load/stream` | admin | Stream model-load progress |
| POST | `/api/admin/models/unload` | admin | Unload models (409 if busy) |
| GET | `/api/admin/logs` | none* | Tail recent JSON logs (filter `service`/`level`/`limit`) |

> *`GET /api/admin/logs` is the one admin handler that does **not** call `require_admin`. In TLS mode it still
> needs a valid token via middleware; in local mode it is fully open. Flagged as a known discrepancy.

### OpenAI-Compatible (`/v1/audio`)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/v1/audio/transcriptions` | user | OpenAI-spec transcription (+ diarization extensions) |
| POST | `/v1/audio/translations` | user | OpenAI-spec translation (always → English) |

### WebSocket
| Endpoint | Auth | Purpose |
|----------|------|---------|
| `/ws` | first message | Longform recording transcription |
| `/ws/live` | first message | Live Mode (sentence-by-sentence) |
| `/api/admin/models/load/stream` | header token, admin | Model-load progress stream |

## Middleware Stack

Effective request-processing order (Starlette applies middleware in reverse registration order):

1. **AuthenticationMiddleware** (TLS mode only) — Bearer/cookie/query-token auth for non-public routes; API → 401 JSON, browser pages → 302 redirect to `/auth`.
2. **OriginValidationMiddleware** — CSRF guard. Allows same-origin / `Origin: null` / `file://` (Electron) / localhost; TLS adds same-host; local mode blocks non-localhost (403).
3. **CORSMiddleware** — permissive headers (`allow_origins=["*"]`); strict enforcement delegated to OriginValidation.

A global `@app.exception_handler(Exception)` returns a generic 500 `{detail:"Internal server error"}`.

## OpenAI-Compatible Audio Endpoints

Both endpoints accept `multipart/form-data` and follow the OpenAI Audio API so drop-in clients work unchanged.

**Standard fields:** `file`, `model`, `language` (transcriptions only), `prompt`, `response_format`, `temperature`, `timestamp_granularities[]`.

**Diarization extension (GH-88):** `diarization` (bool), `expected_speakers` (1–10; out-of-range → 400), `parallel_diarization` (bool, defaults to config).

**Response formats:** `json` (default, `{"text"}`), `text`, `verbose_json`, `srt`, `vtt`, `diarized_json` (extension).

**Speaker-label behavior:** JSON bodies retain raw `SPEAKER_00` labels; subtitle formats normalize to `Speaker 1`. `response_format=json` stays `{"text"}` even with diarization. Word-level speaker assignments appear only when `timestamp_granularities[]=word`.

**Failure tolerance:** if diarization is requested but any stage fails, the endpoint returns 200 with a plain transcript (`num_speakers=0`, no `speaker` keys) and logs a WARNING — never 5xxs on a diarization hiccup.

```bash
curl -F file=@sample.wav -F diarization=true -F expected_speakers=2 \
     -F response_format=diarized_json -H "Authorization: Bearer $TOKEN" \
     http://localhost:9786/v1/audio/transcriptions
```

## WebSocket Protocols

All WS endpoints frame messages as JSON `{type, data, timestamp}`. Binary audio frames use:
**`[4-byte LE metadata length][metadata JSON][PCM Int16 LE]`**.

### `/ws` — Longform / File Transcription
- **Auth:** client → `{type:"auth", data:{token}}`; server → `{type:"auth_ok", data:{client_name, capabilities}}`.
- **Start:** client → `{type:"start", data:{language?, use_vad?, translation_enabled?, translation_target_language?, profile_id?}}`. Slot busy → `{type:"session_busy"}`; else → `{type:"session_started", data:{vad_enabled, job_id, ...}}`.
- **Audio:** binary frames (metadata `{sample_rate}` + PCM); progress via `{type:"processing_progress"}` every 5 s.
- **Stop:** client → `{type:"stop"}`. Result inline `{type:"final", ...}` when ≤1 MB, else `{type:"result_ready", data:{job_id}}` → client fetches `GET /api/transcribe/result/{job_id}`. **Persist-before-deliver:** result saved to DB before send; `mark_delivered` only after inline send.

### `/ws/live` — Live Mode
- **Single session only** — a second connection gets an error + close.
- **Start:** client → `{type:"start", data:{config:{model?, language?, translation_enabled?, silero_sensitivity?, post_speech_silence_duration?}}}`. Server emits `status` during model swap. **Only Whisper (faster-whisper) and whisper.cpp** backends are supported for Live Mode; translation target must be `en` in v1.
- **Streaming output:** `{type:"partial", data:{text}}` (interim), `{type:"sentence", data:{text}}` (final; also fires the `live_sentence` webhook), `{type:"state", data:{state}}`.
- **Stop:** restores main model (status messages) → `{type:"state", data:{state:"STOPPED"}}`. Also: `get_history`/`clear_history`/`ping`.

### `/api/admin/models/load/stream` — Admin Model Load
- **Auth:** header-based (`require_admin`, localhost bypass), no first-message handshake.
- Streams `{type:"progress", message}` then terminal `{type:"complete", status:"loaded"}` or `{type:"error", message}` (BackendDependencyError includes a remedy).

## Authentication

**Token sources** (priority order): `Authorization: Bearer <token>` → `auth_token` cookie → `?token=` query param (notebook audio/export only).

**Token lifecycle:** created via `POST /api/auth/tokens` (admin); plaintext shown once, SHA-256 hash stored; admin tokens never expire, user tokens 30 days; revocable by ID.

**WebSocket auth — two strategies:** auth-by-first-message (`/ws`, `/ws/live`, 10 s timeout, localhost bypass in local mode) and auth-by-headers (admin model-load stream).
