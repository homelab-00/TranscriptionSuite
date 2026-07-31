# GH-254: AI Summary Persistence + Configurable Prompts — Design Spec

Date: 2026-07-30
Branch: `feat/gh254-summary-persistence-and-prompt`, off `main` @ c0a59ec4.
Issue: [#254](https://github.com/homelab-00/TranscriptionSuite/issues/254) —
"Persist AI Summary output and allow custom prompt configuration" (reported
against v1.3.8, Windows).

Supersedes nothing. Touches the same `AudioNoteModal` summary chain that
[2026-06-29-sensevoice-diarization-phase2-design.md](./2026-06-29-sensevoice-diarization-phase2-design.md)
left alone.

## Goal

The issue asks for two things. Investigation showed the first is already
implemented at the persistence layer and broken only at the presentation
layer, and that the second is one config key away from working. Two adjacent
defects surfaced during the investigation and were pulled into scope by the
maintainer:

1. **Show the persisted summary on reopen** — stop making a stored summary
   look like it is being regenerated, and add an explicit Regenerate control.
2. **Make the summary prompt editable** in Settings → AI.
3. **Stop the AI chat from borrowing the summary prompt** (in scope by
   decision — every chat conversation currently opens with the system message
   "Summarize this transcription concisely.").
4. **Delete the dead per-profile summary config** (in scope by decision).

## What the issue got wrong, and why the report is still valid

The reporter states the summary "is discarded when the session is closed".
It is not. `recordings.summary` and `recordings.summary_model` have existed
since the initial schema (001_initial_schema.py:52-53, with 003 backfilling
`summary_model` on older databases), and
`POST /api/llm/summarize/{id}/stream` persists to them on stream completion (commit 236e1272, 2026-04-15 — well before the
v1.3.8 tag of 2026-07-19). `summarize_recording_stream` even persists from
the generator's `finally` block so a client disconnect cannot lose the text.

The regression is entirely in `AudioNoteModal.tsx`:

- Opening the modal runs `setSummaryExpanded(false)` and `setSummaryText('')`
  (AudioNoteModal.tsx:742-743), hiding whatever is stored.
- The collapsed control always reads **"Generate AI Summary"**
  (AudioNoteModal.tsx:2229), with no signal that a stored summary exists.
- Clicking it replays the *stored* text through a `setInterval` typewriter at
  15 ms per character (AudioNoteModal.tsx:861-872). A 2 000-character summary
  takes 30 seconds to "type" — indistinguishable from a real generation, and
  the literal source of "waiting repeatedly for the same output".
- There is no Regenerate. With a stored summary present, the Generate button
  can never reach the LLM; the only path is Clear (`🗑`) followed by Generate.

So the user-visible complaint is real and the fix is a UI fix. No new
persistence, no new column, no migration.

## Decisions taken (and the alternatives rejected)

| Decision | Chosen | Rejected alternative |
|---|---|---|
| Reopen behavior | **Auto-expand, instant render** when a summary is stored. | Stay collapsed with the label changed to "View AI Summary" (still costs a click for something already computed). |
| Stale-summary detection | **Out of scope.** The explicit Regenerate button covers the issue's "or if the transcript content has changed" clause. | A `summary_source_hash` column (migration 018) diffed on load to show a "transcript changed" hint. Deferred, not rejected on merit. |
| Prompt storage | **New `local_llm.summary_system_prompt` key** with a legacy fallback chain. | Expose the existing `default_system_prompt` directly — it is shared with the chat, so editing it would silently retune conversations. |
| Default summary prompt | **Add a language instruction.** | Keep `"Summarize this transcription concisely."` verbatim (leaves the reporter's German-meeting case needing a manual prompt). |
| Chat prompt | **Own key `chat_system_prompt`, editable in Settings.** | Fix the default internally without UI (creates a second invisible hardcoded prompt — the exact complaint in the issue's Feature 2). |
| Dead profile fields | **Delete `summary_prompt_template` + `summary_model_id`.** | Wire them into `EmptyProfileForm` (value would be frozen at creation — recording profiles have no edit UI); or build a profile editor (own feature, roughly doubles this PR). |
| Status endpoint shape | **Four flat fields on `LLMStatus`.** | A nested `prompts` object, or a dedicated `GET /api/llm/prompts`. Cleaner, but `title_generation_prompt` already sits flat there and `SettingsModal` already reads it that way. Noted as a future tidy-up. |

## 1. Prompt configuration (backend)

### 1.1 Constants

`get_llm_config()` (llm.py:169) currently writes the default title prompt out
twice — once in the `try` branch (llm.py:196-207) and once in the exception
fallback (llm.py:223-232). Extract module-level constants and use them in both
branches:

```python
DEFAULT_SUMMARY_SYSTEM_PROMPT = (
    "Summarize this transcription concisely. "
    "Respond in the same language as the transcript."
)
DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions about a transcript. "
    "Base your answers on the transcript provided; if it does not contain "
    "the answer, say so plainly. Respond in the same language as the user's "
    "question."
)
DEFAULT_TITLE_GENERATION_PROMPT = "..."  # verbatim move of the existing text
```

### 1.2 Resolution table

| Key | Consumed by | Chain |
|---|---|---|
| `summary_system_prompt` **(new)** | `/summarize/{id}`, `/summarize/{id}/stream`, `auto_summary_engine` | key → `default_system_prompt` → `DEFAULT_SUMMARY_SYSTEM_PROMPT` |
| `chat_system_prompt` **(new)** | `/api/llm/chat` (llm.py:1643) | key → `default_system_prompt` → `DEFAULT_CHAT_SYSTEM_PROMPT` |
| `default_system_prompt` *(legacy)* | `/process`, `/process/stream` only — no in-app caller | key → `DEFAULT_SUMMARY_SYSTEM_PROMPT` |
| `title_generation_prompt` | `/conversation/{id}/generate-title` | unchanged |

The legacy link is the back-compat guarantee: a `config.yaml` that already
sets `default_system_prompt` produces byte-identical summary *and* chat
behavior after the upgrade. A config that does not set it (every user, since
the key was never exposed in the UI) gets the corrected per-feature defaults.

Every chain uses `or`, not `dict.get(key, default)`, so an empty string falls
through to the built-in. That is what makes "Reset to default" a plain write
rather than a key deletion.

### 1.3 Call-site changes

- `summarize_recording` (llm.py:778) and `summarize_recording_stream`
  (llm.py:848) pass `system_prompt=config["summary_system_prompt"]` into the
  `LLMRequest` they build. Without this they keep inheriting
  `default_system_prompt` via `process_with_llm` (llm.py:445) and
  `_build_llm_stream_response` (llm.py:559).
- `auto_summary_engine.summarize_for_auto_action` (auto_summary_engine.py:71)
  does the same, so automatic and manual summaries cannot diverge.
- `stream_chat` (llm.py:1643) reads `config["chat_system_prompt"]`.

Indexing (`config[...]`) rather than `.get(...)` is deliberate:
`get_llm_config()` always returns the full key set, so the only thing that can
break is a hand-built config dict in a test fixture — which should break
loudly (see §5).

### 1.4 Status endpoint

`LLMStatus` (llm.py:101) and the `_status()` factory (llm.py:259) gain:

```
summary_system_prompt          # effective value
summary_system_prompt_default  # built-in, for "Reset to default"
chat_system_prompt
chat_system_prompt_default
```

Mirrored in `dashboard/src/api/types.ts:444-453`. Returning the defaults from
the server keeps the prompt text in exactly one place — the dashboard never
hardcodes a copy that can drift.

### 1.5 Regenerate needs no backend change

`summarize_recording_stream` never inspects the existing summary; it always
calls the LLM and overwrites on completion. The "don't regenerate" behavior is
purely the client-side `if (recording?.summary)` short-circuit. Regenerate is
therefore just a call to the existing endpoint, and the existing per-recording
409 in-flight guard (llm.py:47-70) already protects against double-clicks.

## 2. Summary UX (`dashboard/components/views/AudioNoteModal.tsx`)

### 2.1 One effect owns the summary state

Delete the `setSummaryExpanded(false)` / `setSummaryText('')` lines from the
open effect (AudioNoteModal.tsx:742-743) and seed from the recording instead,
mirroring the existing `transcript_corrected` seeding effect
(AudioNoteModal.tsx:981-983):

```tsx
useEffect(() => {
  if (!isOpen || isGeneratingRef.current) return;
  const stored = recording?.summary ?? '';
  setSummaryText(stored);
  setSummaryExpanded(!!stored);
}, [isOpen, note?.recordingId, recording?.summary]);
```

Two traps this avoids:

- **Reset and seed must live in the same effect.** The modal stays mounted
  between open and close (it holds `isRendered` for the exit animation), so
  `useRecording` does not refetch when the *same* note is reopened. With the
  reset in the open effect and the seed keyed on `recording?.summary`, the
  seed would not re-run after the reset cleared the text, and the panel would
  come up empty.
- **`isGenerating` must be read through a ref, not a dependency.** As a
  dependency, the effect would re-run when generation finishes and overwrite
  the freshly streamed text with the stale `recording.summary`.

### 2.2 Generation path

- The stored-summary typewriter branch (AudioNoteModal.tsx:861-872) is
  deleted. The `isGenerating` effect keeps only the real LLM stream and the
  "Open a synced recording" fallback for notes without a `recordingId`.
- On stream completion, call `refresh()` from `useRecording` so `summary` and
  `summary_model` match the row, plus the existing `onRecordingMutated?.()`
  for the notebook list.
- On stream failure — network, 502, or the 409 in-flight rejection — show an
  inline error and restore the previous text from `recording.summary`. The row
  is untouched on failure (`_persist_once` skips empty content), so nothing is
  lost; the error must not be left sitting where the summary was.

### 2.3 Controls

New `RotateCw` "Regenerate summary" button in the panel header, next to the
existing `Pencil`. It goes through `confirm()` (the component already has
`useConfirm`, used by `handleClearSummary` at AudioNoteModal.tsx:1063) because
regeneration overwrites hand-edited text.

| State | Collapsed control | Header controls |
|---|---|---|
| No summary | `✨ Generate AI Summary` | — |
| Stored summary | *(none — auto-expanded)* | `↻` `✎` `🗑` |
| Streaming | *(none)* | `⏹` |
| Editing | *(none)* | `✓` `✕` |

`handleClearSummary` already collapses the panel and clears the row
(AudioNoteModal.tsx:1063-1076); after a clear, the seeding effect naturally
returns the panel to the "No summary" row of the table.

## 3. Chat prompt fix

`stream_chat` reads `chat_system_prompt`. No component has ever passed
`ChatRequest.system_prompt` (verified across `dashboard/components` and
`dashboard/src`), so today **every** conversation in the notebook is prefixed
with "Summarize this transcription concisely."

This is a user-visible behavior change for anyone who never customized
`default_system_prompt`. It belongs in the PR body and the release notes.

## 4. Dead profile configuration

`ProfilePublicFields` (profiles.py:99-100) declares `summary_model_id` and
`summary_prompt_template`. Neither is editable anywhere in the dashboard —
`renderProfilesTab` (SettingsModal.tsx:2255) offers create and delete only,
and `apiClient.updateProfile` has no caller. `summary_model_id` is read by
nothing at all; `summary_prompt_template` is read only by
`auto_summary_engine.py:70`, where it can only ever be `None`.

Removal:

- `profiles.py:99-100` — drop both fields.
- `auto_summary_engine.py:70-74` — drop the `custom_prompt` read and the
  `user_prompt=` argument. The request falls back to the standard
  `"Here is the transcription:\n\n{text}"` user message, which is what every
  real run already produced.
- `dashboard/src/api/client.ts:54-63` and
  `dashboard/src/services/profileDefaults.ts:14-27` — drop from the interface
  and the returned literal.
- Fixtures that spell the keys out: `test_profile_repository.py:48-49`,
  `test_create_job_profile_snapshot.py:48-49`,
  `test_reexport_endpoint.py:73-74`, `test_profile_snapshot_durability.py:47-48`,
  `test_delete_recording_artifacts.py:105-106`.

No migration. `public_fields` is a JSON blob and `ProfilePublicFields` sets
`model_config = {"extra": "allow"}`, so keys already stored in existing rows
round-trip untouched as extras and are simply never read again.

## 5. Settings UI (`dashboard/components/views/SettingsModal.tsx`)

New `<Section title="Prompts">` in `renderAITab` (SettingsModal.tsx:1983),
placed after the Model section, holding two textareas:

- **AI Summary Prompt** → `handleAiFieldChange('summary_system_prompt', …)`,
  helper text noting it applies to both manual and automatic summaries.
- **AI Chat Prompt** → `handleAiFieldChange('chat_system_prompt', …)`, helper
  text noting it is the system message that opens every conversation.

Each gets a "Reset to default" `Button` that writes the matching
`*_default` value received from `/status`. New component state
(`aiSummaryPrompt`, `aiChatPrompt`) is seeded in the AI-tab load effect
(SettingsModal.tsx:284-312) exactly as `aiTitlePrompt` is today.

The title prompt stays where it is, inside the auto-title toggle
(SettingsModal.tsx:2120-2147) — it is conditional on that feature being on.

Save flow is untouched: pending `local_llm.*` paths are merged into
`config.yaml` and followed by `POST /api/llm/config/reload`
(SettingsModal.tsx:621-636). Because `get_llm_config()` re-reads `get_config()`
on every call, a prompt edit takes effect on the next summary with no server
restart, despite the generic "restart the server" toast.

## 6. Testing

**Backend** — new `server/backend/tests/test_llm_prompt_config.py`:

- built-in defaults when neither new key nor legacy key is set
- legacy `default_system_prompt` honored by both new chains (back-compat)
- new keys take precedence over the legacy key
- empty string falls through to the built-in (the "Reset to default" contract)
- `/status` returns all four new fields
- `/summarize/{id}` and `/summarize/{id}/stream` send the summary prompt as the
  system message
- `/chat` sends the chat prompt as the system message
- `auto_summary_engine` inherits the summary prompt and sends no `user_prompt`

The two existing `_config()` helpers (`test_p2_llm_routes.py:22`,
`test_llm_summarize_persistence.py:25`) hand-build the config dict and must
gain the new keys. They will `KeyError` first — the intended signal, and the
reason §1.3 indexes instead of using `.get()`.

Run the **full** backend suite from `server/backend/` with the build venv:
`../../build/.venv/bin/pytest tests/ -v --tb=short`.

**Frontend** — vitest (Node 22):

- `AudioNoteModal`: a stored summary renders expanded with the full text and
  no `summarizeRecordingStream` call; Regenerate streams after confirmation;
  an absent summary shows the collapsed "Generate AI Summary" button; a stream
  error restores the previous text. Mocking patterns from
  `components/views/__tests__/AudioNoteModal.auto-actions.test.tsx`.
- `SettingsModal`: both textareas queue their `local_llm.*` keys into pending
  updates; "Reset to default" restores the server-supplied default text.

## 7. Chores

- UI contract (classNames change in two components): `ui:contract:extract` →
  `ui:contract:build` → bump `meta.spec_version` → `validate-contract.mjs
  --update-baseline` → `ui:contract:check`.
- Write `GH-254` in dashboard source comments, never `#254` — the contract
  scanner reads `#254` as a CSS color literal.
- `docs/api-contracts-server.md`: document the four new `LLMStatus` fields.
- Conventional commit style per CLAUDE.md; no AI attribution anywhere.

## Out of scope

- **Stale-summary detection.** Deferred by decision; would need a
  `summary_source_hash` column and migration 018.
- **Per-profile prompts / models.** Blocked on recording profiles having no
  edit UI. Worth its own issue: a profile editor plus per-profile prompt and
  model overrides.
- **`/api/llm/process[/stream]`.** Generic passthrough endpoints with no
  in-app callers; they keep reading `default_system_prompt`.
- **Migrating `LLMStatus` config fields to a dedicated prompts endpoint.**
  Noted in §1.4 as a future tidy-up.
