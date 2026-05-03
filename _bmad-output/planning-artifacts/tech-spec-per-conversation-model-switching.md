# Tech Spec: Per-Conversation Model Switching in Notebook Sidebar

**Issue:** GH-68 follow-up (Ask First item)  
**Date:** 2026-04-10  
**Status:** Draft  

---

## 1. Problem

The AI assistant currently uses a single global model configured in **Settings → AI**. All conversations in every Audio Notebook recording share that model. Users who have access to multiple models (e.g., a fast small model for quick questions, a large model for deep analysis) must go to Settings, change the model, and restart the server to switch — disrupting all active conversations.

## 2. Proposed Solution

Add a model selector to the Notebook AI sidebar that lets users choose which model to use **per conversation**. The selected model is persisted on the conversation record so it's remembered across sessions.

**Resolution order:** Conversation model → Global config model → Auto-detect from provider.

The Settings → AI model remains the default for new conversations. The sidebar selector is an override.

## 3. Database Changes

### 3.1 New Migration: Add `model` Column to `conversations`

File: `server/backend/database/migrations/versions/004_add_conversation_model.py`

```sql
ALTER TABLE conversations ADD COLUMN model TEXT DEFAULT NULL;
```

When `model` is NULL, the conversation uses the global config. When set, it overrides the global config for that conversation's chat requests.

No data backfill needed — existing conversations get NULL (use global default).

### 3.2 Database Functions

**`server/backend/database/database.py`**

| Function | Change |
|----------|--------|
| `create_conversation(recording_id, title)` | Add optional `model: str \| None = None` parameter, write to new column |
| `get_conversations(recording_id)` | Already uses `SELECT *` — new column returned automatically |
| `get_conversation_with_messages(id)` | Already uses `SELECT *` — new column returned automatically |
| New: `update_conversation_model(id, model)` | `UPDATE conversations SET model = ?, updated_at = ? WHERE id = ?` |

## 4. Backend API Changes

### 4.1 Pydantic Models

**`server/backend/api/routes/llm.py`**

```python
class ConversationCreate(BaseModel):
    recording_id: int
    title: str | None = "New Chat"
    model: str | None = None          # NEW — optional model override

class ConversationUpdate(BaseModel):
    title: str | None = None          # CHANGED — now optional
    model: str | None = None          # NEW — set/clear model override

class ChatRequest(BaseModel):
    conversation_id: int
    user_message: str
    system_prompt: str | None = None
    include_transcription: bool = True
    max_tokens: int | None = None
    temperature: float | None = None
    model: str | None = None          # NEW — per-request model override
```

### 4.2 Endpoint Changes

**`POST /api/llm/conversations`** — Accept optional `model` field, pass to `create_conversation()`.

**`PATCH /api/llm/conversation/{id}`** — Accept optional `model` field (alongside existing `title`). Call `update_conversation_model()` when provided. Sending `model: null` clears the override (reverts to global default). Sending `model: ""` also clears it.

**`GET /api/llm/conversation/{id}`** and **`GET /api/llm/conversations/{recording_id}`** — Already return all columns via `SELECT *`, so `model` will appear automatically. No code change needed.

**`POST /api/llm/chat`** — Change model resolution:

```python
# Current:
model_id = config.get("model")
if not model_id:
    model_id = await _get_loaded_model_id(base_url, headers)

# New (3-tier fallback):
# 1. Per-request override (from ChatRequest.model)
model_id = request.model
# 2. Per-conversation override (from DB)
if not model_id:
    model_id = conversation.get("model")
# 3. Global config
if not model_id:
    model_id = config.get("model")
# 4. Auto-detect from provider
if not model_id:
    model_id = await _get_loaded_model_id(base_url, headers)
```

The per-request `model` field in `ChatRequest` allows the frontend to send a one-off override without persisting it. In practice the frontend will typically set the model on the conversation and let the chat endpoint pick it up from the DB (tier 2).

## 5. Frontend Changes

### 5.1 TypeScript Types

**`dashboard/src/api/types.ts`**

```typescript
// Add to existing interfaces:
export interface Conversation {
  // ... existing fields ...
  model?: string | null;       // NEW
}

export interface ChatRequest {
  // ... existing fields ...
  model?: string;              // NEW — per-request override
}
```

**`dashboard/components/views/AudioNoteModal.tsx`**

```typescript
// Add to ChatSession interface:
interface ChatSession {
  // ... existing fields ...
  model?: string | null;       // NEW — persisted model override
}
```

### 5.2 API Client

**`dashboard/src/api/client.ts`**

- `createConversation(recordingId, title, model?)` — add optional `model` parameter
- `updateConversation(id, title?, model?)` — change to accept partial updates (title and/or model)
- `chat(request)` — the request type already gains `model?` from the types change

### 5.3 Sidebar UI

**`dashboard/components/views/AudioNoteModal.tsx`**

**Model selector location:** Below the status indicator in the sidebar header, next to the model name display. Replaces the static `Model: {llmModel}` text with an interactive element.

**Component design:**

```
┌─────────────────────────────┐
│  🤖 AI Assistant            │
│  ● Online                   │
│  Model: [gpt-4o        ▾]  │  ← clickable selector
│─────────────────────────────│
│  Chat sessions...           │
```

**Behavior:**

1. **Default state (no conversation selected):** Shows the global model from LLM status. Selector is disabled.

2. **Conversation selected, no override:** Selector shows the global model in dimmed text with placeholder "(using default)". Clicking opens a dropdown/datalist.

3. **Conversation selected, override set:** Selector shows the override model. A small "×" button clears the override.

4. **Model list:** Populated from `apiClient.getAvailableModels()` (cached after first fetch). Falls back to manual text entry if discovery fails — same datalist pattern as Settings → AI tab.

5. **On model change:** Call `apiClient.updateConversation(id, undefined, newModel)` to persist. Update the local `ChatSession` state. Subsequent messages use the new model.

6. **New conversation:** Inherits no model override (uses global default). User can change after creation.

**State additions:**

```typescript
const [availableModels, setAvailableModels] = useState<LLMModel[]>([]);
const [modelsLoaded, setModelsLoaded] = useState(false);
```

Models are fetched once when the sidebar opens (or lazily on first dropdown open) and cached for the session.

### 5.4 Visual Indicator

When a conversation uses a non-default model, show a subtle visual cue in the session list so users can tell at a glance which conversations have overrides:

```
  💬 Chat about quarterly results     14:30
  💬 Quick summary  [gpt-4o-mini]     14:25    ← model tag shown
  💬 Detailed analysis                14:20
```

A small badge/tag next to the session title showing the model name, only when it differs from the global default.

## 6. Migration Strategy

- **Database:** Standard Alembic migration (ALTER TABLE ADD COLUMN). Non-destructive — NULL default means existing conversations are unaffected.
- **API:** All new fields are optional with NULL/None defaults. Fully backward compatible.
- **Frontend:** The selector is additive UI. Existing behavior is unchanged when no override is set.
- **No server restart required** for model switching — the model ID is sent directly in the `/v1/chat/completions` payload. The provider resolves the model server-side.

## 7. Edge Cases

| Scenario | Behavior |
|----------|----------|
| Conversation model deleted from provider | Chat returns provider's error (e.g., "model not found"). Sidebar shows the stale model name. User can clear the override or pick a new model. |
| Provider unreachable when fetching models | Dropdown empty, manual text entry available. Existing override still works. |
| User clears override mid-conversation | Next message uses global default. Prior messages (stored with their model in the `messages` table) retain their original model attribution. |
| Model override set but API key invalid for that model | Provider returns 401/403. Streamed as error event to frontend. Same handling as any chat error. |
| Concurrent tabs, same conversation | Last-write-wins on the conversation model. Chat requests read from DB at call time. |

## 8. Acceptance Criteria

1. Given a conversation with no model override, when a user sends a message, then the global config model is used (existing behavior, unchanged).
2. Given a conversation where the user selects a different model from the dropdown, when they send a message, then the selected model is used in the `/v1/chat/completions` request.
3. Given a conversation with a model override, when the user closes and reopens the Notebook, then the override is still shown (persisted in DB).
4. Given a conversation with a model override, when the user clears the override, then subsequent messages use the global config model.
5. Given the model selector dropdown, when the user clicks refresh, then the available models from the provider are listed.
6. Given a provider that doesn't support `/v1/models`, when the dropdown fails, then the user can manually type a model ID.

## 9. Files to Modify

| File | Change |
|------|--------|
| `server/backend/database/migrations/versions/004_add_conversation_model.py` | **New** — migration |
| `server/backend/database/database.py` | Add `model` param to `create_conversation`, add `update_conversation_model` |
| `server/backend/api/routes/llm.py` | Update `ConversationCreate`, `ConversationUpdate`, `ChatRequest` models; update model resolution in `chat_with_llm`; update `create_conversation` and `update_conversation` handlers |
| `dashboard/src/api/types.ts` | Add `model?` to `Conversation`, `ChatRequest` |
| `dashboard/src/api/client.ts` | Update `createConversation`, `updateConversation`, `chat` signatures |
| `dashboard/components/views/AudioNoteModal.tsx` | Add model selector UI, model state, `ChatSession.model` field, session list model badges |

## 10. Out of Scope

- **Per-conversation API key / endpoint URL** — all conversations use the same provider. Supporting multiple providers simultaneously is a separate feature.
- **Model-specific parameters** (temperature, max_tokens per model) — can be added later.
- **Model capability detection** (e.g., context window limits) — defer until needed.
- **Conversation forking** (switch model mid-conversation and branch history) — messages are linear.
