# TranscriptionSuite — API Contracts (Server)

> Generated: 2026-04-05 | Base URL: `http(s)://host:9786`

## Endpoint Summary

### Health & Status (no auth)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Lightweight liveness probe |
| GET | `/ready` | Readiness (200 when models loaded, 503 when loading) |
| GET | `/api/status` | Detailed server status (GPU, model, features) |

### Authentication
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/auth/login` | No | Authenticate with token |
| GET | `/api/auth/tokens` | Admin | List active tokens |
| POST | `/api/auth/tokens` | Admin | Create new token (plaintext returned once) |
| DELETE | `/api/auth/tokens/{token_id}` | Admin | Revoke token |

### Transcription
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/transcribe/audio` | Yes | Transcribe uploaded audio/video file |
| POST | `/api/transcribe/quick` | Yes | Quick transcription (simplified params) |
| POST | `/api/transcribe/cancel` | Yes | Cancel in-progress transcription |
| POST | `/api/transcribe/import` | Yes | Import file to notebook with transcription |
| GET | `/api/transcribe/languages` | Yes | List supported languages |
| GET | `/api/transcribe/result/{job_id}` | Yes | Poll for transcription result (durability) |

### Audio Notebook
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/notebook/recordings` | Yes | List all recordings |
| GET | `/api/notebook/recordings/{id}` | Yes | Get recording with segments/words |
| POST | `/api/notebook/recordings` | Yes | Upload and transcribe for notebook |
| DELETE | `/api/notebook/recordings/{id}` | Yes | Delete recording + audio |
| GET | `/api/notebook/recordings/{id}/audio` | Yes* | Download original audio |
| GET | `/api/notebook/recordings/{id}/export` | Yes* | Export as SRT/VTT/ASS |
| PATCH | `/api/notebook/recordings/{id}/title` | Yes | Update title |
| PATCH | `/api/notebook/recordings/{id}/recorded_at` | Yes | Update recording date |
| PATCH | `/api/notebook/recordings/{id}/summary` | Yes | Update summary |
| PUT | `/api/notebook/recordings/{id}/summary` | Yes | Set summary + model name |
| POST | `/api/notebook/transcribe/upload` | Yes | Upload to notebook |
| GET | `/api/notebook/calendar` | Yes | Recordings grouped by date |
| GET | `/api/notebook/timeslot` | Yes | Check time slot conflicts |
| GET | `/api/notebook/backups` | Yes | List database backups |
| POST | `/api/notebook/backup` | Yes | Create backup |
| POST | `/api/notebook/restore` | Yes | Restore from backup |

*Audio/export endpoints also accept `?token=...` query parameter.

### Search
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/search` | Yes | Full-text search (FTS5) |
| GET | `/api/search/words` | Yes | Word-level search with timestamps |
| GET | `/api/search/recordings` | Yes | Search recording metadata |

### LLM Integration
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/llm/status` | Yes | LM Studio connection status |
| POST | `/api/llm/process` | Yes | Process text with LLM |
| POST | `/api/llm/process/stream` | Yes | Streaming LLM processing |
| POST | `/api/llm/summarize/{id}` | Yes | Summarize recording |
| POST | `/api/llm/summarize/{id}/stream` | Yes | Streaming summarization |
| GET | `/api/llm/models/available` | Yes | List available LLM models |
| POST | `/api/llm/model/load` | Yes | Load LLM model |
| POST | `/api/llm/model/unload` | Yes | Unload LLM model |
| POST | `/api/llm/server/start` | Yes | Start LM Studio server |
| POST | `/api/llm/server/stop` | Yes | Stop LM Studio server |

### Admin
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/admin/status` | Admin | Detailed model/config status |
| GET | `/api/admin/config/full` | Admin | Full server configuration |
| PATCH | `/api/admin/config` | Admin | Update config key-value pairs |
| PATCH | `/api/admin/diarization` | Admin | Update diarization settings |
| POST | `/api/admin/models/load` | Admin | Load specific model |
| WS | `/api/admin/models/load/stream` | Admin | Stream model loading progress |
| POST | `/api/admin/models/unload` | Admin | Unload current model |
| POST | `/api/admin/webhook/test` | Admin | Test webhook endpoint |
| GET | `/api/admin/logs` | Admin | Stream server logs (WebSocket) |

### OpenAI-Compatible
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/v1/audio/transcriptions` | Yes | OpenAI-compatible transcription |
| POST | `/v1/audio/translations` | Yes | OpenAI-compatible translation |

### WebSocket Protocols
| Endpoint | Auth | Purpose |
|----------|------|---------|
| `/ws` | Token (first message) | Longform recording transcription |
| `/ws/live` | Token (first message) | Real-time live transcription |

## WebSocket Protocol — Longform (`/ws`)

**Auth:** First message must be `{authenticate: "<token>"}`

**Start:** `{start: {language: "en", device: "cuda", translate: false, diarization: true}}`

**Audio:** Binary PCM Int16 frames

**Stop:** `{stop: true}`

**Result:** `{result: {segments: [...], words: [...], language: "en", duration: 45.2}}`

## WebSocket Protocol — Live Mode (`/ws/live`)

**Auth:** Same as longform (first message)

**Start:** `{start: {language: "en", translate: false}}`

**Audio:** Continuous PCM Int16 binary chunks

**Partial results:** `{type: "partial", text: "I'm currently..."}`

**Final segments:** `{type: "sentence", text: "I'm currently speaking."}`

**Stop:** `{stop: true}` → `{result: final_transcript}`

## Authentication

**Token sources** (checked in priority order):
1. `Authorization: Bearer <token>` header
2. `auth_token` cookie
3. `?token=<token>` query param (notebook audio/export only)

**Token lifecycle:**
- Created via `POST /api/auth/tokens` (admin only)
- Plaintext shown once at creation, SHA-256 hash stored
- Admin tokens: never expire
- User tokens: 30-day expiry
- Revocable by token ID via `DELETE /api/auth/tokens/{token_id}`
