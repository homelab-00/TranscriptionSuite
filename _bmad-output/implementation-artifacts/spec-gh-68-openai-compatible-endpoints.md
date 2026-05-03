---
title: 'GH-68: OpenAI-Compatible Endpoint Support'
type: 'feature'
created: '2026-04-10'
status: 'done'
baseline_commit: 'fa908bd'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Audio Notebook AI features (chat and summarization) only work with LM Studio. Users who want commercial providers (OpenAI, Groq, OpenRouter) or other local tools (Ollama, Open WebUI) cannot use them because there is no API key support, no model selection UI, and the chat endpoint uses a LM Studio-specific API (`/api/v1/chat` with `response_id`).

**Approach:** Add API key configuration, switch chat to standard `/v1/chat/completions` with full message history (works with all providers including LM Studio), add model discovery via `/v1/models`, create a dedicated Settings "AI" tab for endpoint/key/model config, and update UI labels from "LM Studio" to generic branding.

## Boundaries & Constraints

**Always:**
- Send `Authorization: Bearer {api_key}` header when `api_key` is non-empty
- Include `"model"` field in all `/v1/chat/completions` payloads (required by most providers)
- Use standard `/v1/chat/completions` for both chat and summarization (drop LM Studio-specific `/api/v1/chat`)
- Keep backward compat — existing configs with no `api_key` continue to work; keep `local_llm` config key
- Support `LLM_API_KEY` env var override for Docker deployments

**Ask First:**
- Whether to add per-conversation model switching in the Notebook sidebar (current spec: Settings only)

**Never:**
- Provider-specific adapters (native Anthropic/Gemini API) — OpenAI-compat only
- Multiple simultaneous provider profiles
- Remove or rename the `local_llm` config section key

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Local LM Studio, no key | `api_key` empty, `base_url` localhost | Works as before, no auth header | N/A |
| Remote provider with key | `api_key` set, `base_url` = provider | Auth header included, model field sent | 401 → "Invalid API key" message |
| Model discovery succeeds | Provider returns `/v1/models` list | Settings dropdown populated | N/A |
| Provider lacks `/v1/models` | 404 or timeout from provider | Fall back to manual model ID text input | Non-blocking warning |
| Empty model field, remote provider | No model configured | Request sent without model field | Provider returns 4xx → "Please select a model in Settings" |

</frozen-after-approval>

## Code Map

- `server/backend/api/routes/llm.py` — LLM routes, config loading (`get_llm_config`), chat endpoint, summarize endpoints
- `server/config.yaml` — `local_llm` section (add `api_key` field)
- `dashboard/components/views/SettingsModal.tsx` — Tab-based settings (add "AI" tab)
- `dashboard/components/views/AudioNoteModal.tsx` — LLM sidebar with "LM Studio" label and status display
- `dashboard/src/api/client.ts` — API client methods for LLM endpoints
- `dashboard/src/api/types.ts` — TypeScript types for LLM status, models, chat
- `dashboard/components/views/AboutModal.tsx` — App description mentioning LM Studio

## Tasks & Acceptance

**Execution:**
- [x] `server/config.yaml` — Add `api_key: ""` to `local_llm` section
- [x] `server/backend/api/routes/llm.py` — Extend `get_llm_config()` with `api_key` (env var `LLM_API_KEY` override); build shared `_get_headers()` helper that returns `Authorization: Bearer` when key present; add `"model"` to all `/v1/chat/completions` payloads
- [x] `server/backend/api/routes/llm.py` — Add `GET /api/llm/models` endpoint that proxies the provider's `GET /v1/models` and returns a simplified list
- [x] `server/backend/api/routes/llm.py` — Refactor `POST /api/llm/chat` from LM Studio `/api/v1/chat` with `response_id` to standard `/v1/chat/completions` with full message history from DB
- [x] `dashboard/src/api/types.ts` — Update `LLMModel` and `LLMModelsResponse` types to match new backend
- [x] `dashboard/src/api/client.ts` — Add `getAvailableModels()` method (config saves via existing serverConfigUpdates flow)
- [x] `dashboard/components/views/SettingsModal.tsx` — Add "AI" tab: endpoint URL input, API key (masked), model input with datalist (populated from `/api/llm/models` with manual-entry fallback), enabled toggle
- [x] `dashboard/components/views/AudioNoteModal.tsx` — Rename "LM Studio" → "AI Assistant" in sidebar header; keep status light and model display
- [x] `dashboard/components/views/AboutModal.tsx` — Update description: "LM Studio integration" → "AI assistant (OpenAI-compatible)"
- [x] Unit-test edge cases from I/O matrix (401 handling, missing model field, model discovery fallback)

**Acceptance Criteria:**
- Given a remote OpenAI-compatible endpoint with API key, when configured in Settings and a chat message is sent, then the response streams back successfully
- Given no API key and a local LM Studio, when a user chats or summarizes, then the system works identically to before
- Given the Settings AI tab, when endpoint URL and key are entered and "Refresh" is clicked, then available models populate the dropdown
- Given a provider that does not support `/v1/models`, when the dropdown fails to load, then a manual model ID text input is shown

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` — expected: no TypeScript errors
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` — expected: all existing tests pass

**Manual checks:**
- Settings "AI" tab renders with endpoint URL, API key, model dropdown, and enabled toggle
- AudioNoteModal sidebar header reads "AI Assistant" instead of "LM Studio"
- Chat and summarization work with both local LM Studio (no key) and a remote endpoint (with key)

## Suggested Review Order

**Config & Auth**

- API key field added, env var `LLM_API_KEY` override, updated comments
  [`config.yaml:352`](../../server/config.yaml#L352)

- `get_llm_config()` gains `api_key`; new `_get_headers()` builds Bearer auth
  [`llm.py:122`](../../server/backend/api/routes/llm.py#L122)

**Provider-agnostic status & model discovery**

- Status endpoint: explicit-model fast-path, /v1/models → /api/v0/models fallback
  [`llm.py:174`](../../server/backend/api/routes/llm.py#L174)

- New `GET /models` endpoint proxies provider's model list
  [`llm.py:274`](../../server/backend/api/routes/llm.py#L274)

**Chat refactor (key architectural change)**

- Chat switched from LM Studio `/api/v1/chat` to standard `/v1/chat/completions` with full DB message history
  [`llm.py:1198`](../../server/backend/api/routes/llm.py#L1198)

**Frontend Settings UI**

- New "AI" tab: endpoint URL, masked API key, model input with datalist, enabled toggle
  [`SettingsModal.tsx:1529`](../../dashboard/components/views/SettingsModal.tsx#L1529)

- AI tab state + data loading effect
  [`SettingsModal.tsx:119`](../../dashboard/components/views/SettingsModal.tsx#L119)

**UI label changes**

- Sidebar header: "LM Studio" → "AI Assistant"
  [`AudioNoteModal.tsx:1507`](../../dashboard/components/views/AudioNoteModal.tsx#L1507)

- About modal: "LM Studio integration" → "AI assistant (OpenAI-compatible)"
  [`AboutModal.tsx:127`](../../dashboard/components/views/AboutModal.tsx#L127)

**Types & API client**

- `LLMModel` simplified for generic providers; `LLMModelsResponse` keeps old fields optional
  [`types.ts:387`](../../dashboard/src/api/types.ts#L387)

- New `getAvailableModels()` client method
  [`client.ts:749`](../../dashboard/src/api/client.ts#L749)

**Tests**

- 8 new edge case tests: auth headers, 401 handling, model discovery
  [`test_p2_llm_routes.py:228`](../../server/backend/tests/test_p2_llm_routes.py#L228)
