---
title: 'Per-Conversation Model Switching'
type: 'feature'
created: '2026-04-10'
status: 'done'
baseline_commit: '7369aa1'
context: ['docs/api-contracts-server.md', 'docs/data-models-server.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** All Notebook AI conversations share a single global model from Settings → AI. Users with access to multiple models (fast small model for quick questions, large model for deep analysis) must change Settings and restart the server to switch — disrupting all active conversations.

**Approach:** Add a model selector to the Notebook AI sidebar per conversation. The selected model is persisted on the conversation record (DB column) with a 3-tier resolution: conversation override → global config → auto-detect from provider.

## Boundaries & Constraints

**Always:**
- NULL model column = use global default (backward compatible)
- Sending `model: null` or `model: ""` via PATCH clears the override
- All new fields are optional — existing API callers unaffected
- Model list populated from `getAvailableModels()` with manual text entry fallback

**Ask First:**
- Any schema change beyond the single `model TEXT` column on conversations
- Adding per-conversation API key or endpoint URL (out of scope)

**Never:**
- Break existing conversations (NULL default preserves current behavior)
- Require server restart for model switching
- Add per-model parameter tuning (temperature/max_tokens per model) — future work

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No override set | conversation.model = NULL | Uses global config model | Falls through to auto-detect if config empty |
| Override set | conversation.model = "gpt-4o-mini" | Chat uses "gpt-4o-mini" in /v1/chat/completions | Provider returns model-not-found → surface to user |
| Clear override | PATCH model: null | conversation.model set to NULL, next chat uses global | N/A |
| Provider unreachable for model list | getAvailableModels() fails | Dropdown empty, manual text input available | Existing override still works |
| Override set, API key invalid for model | Chat sent with overridden model | Provider returns 401/403 | Streamed as error event to frontend |

</frozen-after-approval>

## Code Map

- `server/backend/database/migrations/versions/007_add_conversation_model.py` -- **New** migration: `ALTER TABLE conversations ADD COLUMN model TEXT DEFAULT NULL`
- `server/backend/database/database.py` -- Add `model` param to `create_conversation`; add `update_conversation_model` function
- `server/backend/api/routes/llm.py` -- Update Pydantic models + handlers + 3-tier model resolution in `chat_with_llm`
- `dashboard/src/api/types.ts` -- Add `model?` to `Conversation` and `ChatRequest` interfaces
- `dashboard/src/api/client.ts` -- Add `model?` param to `createConversation`, `updateConversation`; update signatures
- `dashboard/components/views/AudioNoteModal.tsx` -- Model selector UI, `ChatSession.model`, session list badges
- `server/backend/tests/test_database.py` -- Add `model TEXT` to test schema for conversations table

## Tasks & Acceptance

**Execution:**
- [x] `server/backend/database/migrations/versions/007_add_conversation_model.py` -- Create migration adding `model TEXT DEFAULT NULL` to conversations table
- [x] `server/backend/database/database.py` -- Add optional `model` param to `create_conversation()`; add `update_conversation_model(id, model)` function
- [x] `server/backend/api/routes/llm.py` -- Add `model` field to `ConversationCreate`, `ConversationUpdate`, `ChatRequest`; update `create_conversation_endpoint` and `update_conversation_endpoint` handlers; implement 3-tier model resolution in `chat_with_llm`
- [x] `dashboard/src/api/types.ts` -- Add optional `model` field to `Conversation` and `ChatRequest` interfaces
- [x] `dashboard/src/api/client.ts` -- Add optional `model` param to `createConversation()` and refactor `updateConversation()` to accept partial updates (title and/or model)
- [x] `dashboard/components/views/AudioNoteModal.tsx` -- Add `model` to ChatSession; replace static model text with interactive selector; add model badges to session list; fetch and cache available models
- [x] `server/backend/tests/test_database.py` -- Add `model TEXT` column to conversations CREATE TABLE in test schema
- [x] `server/backend/tests/test_p2_llm_routes.py` -- Add tests for model override in create, update, and chat endpoints

**Acceptance Criteria:**
- Given a conversation with no model override, when a user sends a message, then the global config model is used (unchanged behavior)
- Given a conversation with model override set, when a user sends a message, then the overridden model is used in the /v1/chat/completions request
- Given a model override, when the user closes and reopens the Notebook, then the override is still shown (persisted in DB)
- Given a model override, when the user clears it, then subsequent messages use the global config model
- Given the model dropdown, when clicked, then available models from the provider are listed (with manual text entry fallback)

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_database.py tests/test_p2_llm_routes.py -v --tb=short` -- expected: all pass
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors

## Suggested Review Order

**Data layer**

- New column with NULL default — backward compatible, no backfill
  [`007_add_conversation_model.py:38`](../../server/backend/database/migrations/versions/007_add_conversation_model.py#L38)

- `create_conversation` gains optional `model` param; new `update_conversation_model`
  [`database.py:630`](../../server/backend/database/database.py#L630)

- Schema sanity check updated to include `model`
  [`database.py:181`](../../server/backend/database/database.py#L181)

- Public API export for new function
  [`__init__.py:11`](../../server/backend/database/__init__.py#L11)

**3-tier model resolution (core design)**

- Per-request → per-conversation → global config → auto-detect chain
  [`llm.py:1224`](../../server/backend/api/routes/llm.py#L1224)

**API endpoints**

- Pydantic models: `model` field on Create, Update, ChatRequest
  [`llm.py:1037`](../../server/backend/api/routes/llm.py#L1037)

- `update_conversation`: `model_fields_set` distinguishes null-sent from absent
  [`llm.py:1138`](../../server/backend/api/routes/llm.py#L1138)

- `create_conversation`: passes model to DB, returns it in response
  [`llm.py:1098`](../../server/backend/api/routes/llm.py#L1098)

**Frontend integration**

- Type additions: `model?` on `Conversation` and `ChatRequest`
  [`types.ts:417`](../../dashboard/src/api/types.ts#L417)

- Client: `updateConversation` now takes `{title?, model?}` updates object
  [`client.ts:803`](../../dashboard/src/api/client.ts#L803)

- Model selector dropdown in sidebar footer (replaces static text)
  [`AudioNoteModal.tsx:1722`](../../dashboard/components/views/AudioNoteModal.tsx#L1722)

- Model badges on session list items when override differs from global
  [`AudioNoteModal.tsx:1615`](../../dashboard/components/views/AudioNoteModal.tsx#L1615)

- Model state, handlers, and click-away logic
  [`AudioNoteModal.tsx:826`](../../dashboard/components/views/AudioNoteModal.tsx#L826)

**Tests**

- DB round-trip tests for model create, update, and clear
  [`test_database.py:555`](../../server/backend/tests/test_database.py#L555)

- Pydantic model tests: field acceptance, defaults, `model_fields_set`
  [`test_p2_llm_routes.py:333`](../../server/backend/tests/test_p2_llm_routes.py#L333)
