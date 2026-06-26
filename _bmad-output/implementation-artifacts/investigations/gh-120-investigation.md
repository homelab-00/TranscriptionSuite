# Investigation: GH #120 — "Possible duplicate detected" pop-up impedes batch / Folder Watch processing

## Hand-off Brief

1. **What happened.** During unattended Folder Watch / batch import, every re-imported file that
   matches a previously-transcribed file's audio hash raises a blocking, interactive "Possible
   duplicate detected" modal that stalls the whole import queue until a human clicks — confirmed
   reproducible by code path (`dashboard/src/stores/importQueueStore.ts:303`).
2. **Where the case stands.** **Concluded — bug is STILL PRESENT (High confidence).** Five
   independent adversarial lenses (frontend, backend, settings/config/env, other-surfaces, git/test
   history) all failed to refute it; no escape hatch (setting, flag, env, auto-resolve, or job-type
   branch) exists anywhere. Issue is still OPEN on GitHub; no commit/PR/branch references #120.
3. **What's needed next.** Add an **unattended duplicate policy** for `session-auto` (Folder Watch)
   jobs — a per-job choice resolved without the modal (default: *create new*), surfaced as a
   setting (Ask / Always create new / Always skip). Implementation is a small, well-scoped change.

## Case Info

| Field            | Value                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------- |
| Ticket           | GH #120 (OPEN, label: bug). Filed 2026-05-12.                                            |
| Date opened      | 2026-06-26                                                                              |
| Status           | Concluded                                                                               |
| System           | Electron dashboard (React/TS) + FastAPI server. Folder Watch / batch import workflow.   |
| Evidence sources | GitHub issue + screenshot; current source (dashboard + server); git history; test suite |

## Problem Statement

User ran an overnight batch via "Folder watch". Some files transcribed successfully; the run then
stopped. To resume, the user created a new watch folder, placed remaining audio files, and waited.
Instead of processing unattended, a **"Possibe duplicate detected. This recording matches an existing
one: 'c3b4c22a' from 5/7/2026. Use the existing transcript, or create a new entry?"** modal popped up
for *each* file, requiring a manual choice every time. Net effect: the batch can no longer run
unsupervised. (User also asked, secondarily, how to delete the existing recordings.)

## Evidence Inventory

| Source                                   | Status    | Notes                                                                 |
| ---------------------------------------- | --------- | --------------------------------------------------------------------- |
| GitHub issue #120 + screenshot           | Available | Modal copy matches `DedupPromptModal.tsx:62,67,77` verbatim           |
| `dashboard/src/stores/importQueueStore.ts` | Available | Root cause: `processSessionJob` dedup gate (lines 303–329)            |
| `dashboard/src/stores/dedupChoiceStore.ts` | Available | Promise resolves only via interactive modal — no auto/timeout         |
| `dashboard/components/import/*`            | Available | `DedupChoiceContainer`, `DedupPromptModal` — purely interactive        |
| `server/backend/api/routes/transcription.py` | Available | `/import` always returns `dedup_matches` (lines 1247–1261, 1301)      |
| Dashboard config store / Electron defaults | Available | No dedup policy key (`store.ts`, `main.ts:533`)                        |
| `SettingsModal.tsx`                       | Available | No dedup/duplicate control                                            |
| Server `config.py` / `config.yaml`        | Available | No dedup config key; no DEDUP/SKIP_DEDUP env var                      |
| Test suite (dedup + importQueue)          | Available | Only interactive choice covered; no unattended-bypass test            |
| Git history (all branches)                | Available | Flow introduced under #104 (`4ac23e60`, 2026-05-04); #120 unaddressed |

## Confirmed Findings

### Finding 1: The dedup gate blocks the import queue for ALL session jobs, including Folder Watch

**Evidence:** `dashboard/src/stores/importQueueStore.ts:303-329`

**Detail:** Inside `processSessionJob`, after `importAndTranscribe`, the code does
`if (importResponse.dedup_matches?.length) { const choice = await useDedupChoiceStore.getState().requestChoice(...) }`.
This branch is keyed *only* on `dedup_matches.length` — there is **no** check on `job.type`. The
serial `processQueue` while-loop (`importQueueStore.ts:418-471`) `await`s `processSessionJob`, so a
single unanswered modal halts the entire batch.

### Finding 2: Folder Watch (`session-auto`) jobs run the identical blocking path as manual jobs

**Evidence:** `importQueueStore.ts:426` (`isSession = type === 'session-normal' || 'session-auto'`),
`:437-438` (both routed to `processSessionJob`), `:702` (watcher enqueues `'session-auto'`).

**Detail:** `handleFilesDetected(type:'session')` enqueues `session-auto` jobs that flow through the
same `processSessionJob`, so unattended watched files hit the same interactive modal as manual imports.

### Finding 3: The dedup-choice promise can only be resolved by a human

**Evidence:** `dashboard/src/stores/dedupChoiceStore.ts:43-63`; `DedupChoiceContainer.tsx:20-23`;
`App.tsx:821`.

**Detail:** `requestChoice` returns a Promise resolved exclusively by `resolveChoice`, which is called
only by the interactive `DedupPromptModal` (button click / Esc / backdrop close). There is **no
timeout, no default choice, no programmatic/unattended resolver.** The queue therefore blocks
indefinitely until a person clicks.

### Finding 4: The server returns `dedup_matches` unconditionally — no suppression knob

**Evidence:** `server/backend/api/routes/transcription.py:1247-1261` and `:1301`; Form signature at
`:1153-1164` (no skip/force/auto param); `dedup_query.py:59`; `job_repository.py:114`.

**Detail:** `/api/transcribe/import` computes `audio_hash` + `normalized_audio_hash` and calls
`find_duplicates_anywhere` whenever either hash exists, returning matches inline. There is no Form
field, config key, env var, or per-client setting to suppress it. The client
(`importAndTranscribe`, `client.ts:830-850`) sends no such parameter, and `TranscriptionUploadOptions`
(`types.ts:104`) defines none.

### Finding 5: No user-facing setting / config / env mitigates this anywhere

**Evidence:** `dashboard/src/config/store.ts` (no dedup key); `dashboard/electron/main.ts:533`
(`folderWatch.*` = only `sessionPath`/`notebookPath`/`sessionWatchActive`/`notebookWatchActive`);
`SettingsModal.tsx` (no control); `server` config (no key/env). Exhaustive repo-wide grep for
~16 plausible knob names returned no real match.

### Finding 6: Issue is unaddressed in code/history; tests don't cover an unattended bypass

**Evidence:** Issue #120 still OPEN. No commit/PR/branch references #120 (git `--all --grep`,
`git grep`). Flow introduced under **#104**, commit `4ac23e60` (2026-05-04), building on `8839d67e`.
Tests (`DedupPromptModal.test.tsx`, `dedupChoiceStore.test.ts`, `DedupChoiceContainer.test.tsx`,
`importQueueStore.test.ts`) cover only the interactive choice; none asserts session-auto auto-resolve.

## Deduced Conclusions

### Deduction 1: The bug is structural, not a regression or matching glitch

**Based on:** Findings 1–6.

**Reasoning:** The interactive modal is the *only* code path that resolves a duplicate, and it is
reachable by `session-auto` jobs with no differentiation. Dedup detection on the server is
unconditional whenever audio content matches a prior persisted row (raw or normalized PCM SHA-256).
The matching itself is correct (exact-content), so the problem isn't false positives — it's that the
*only* resolution mechanism is a blocking human prompt.

**Conclusion:** Any Folder Watch / batch run that re-imports audio already transcribed in a prior run
(or duplicated across files) will stall on the modal. This exactly reproduces issue #120.

## Hypothesized Paths

### Hypothesis 1: A double-detection within a single fresh batch could also trigger the prompt

**Status:** Open (not required to confirm the bug; documented for completeness)

**Theory:** Because each `/import` creates a durability row carrying the hash *before* the next file
is processed, if the watcher were to detect the same file twice (file still being written, rapid
re-scan), the second import could match the first and prompt — even with no prior run.

**Supporting indicators:** Row-with-hash is created at import time (`transcription.py:1234-1261`).

**Would confirm:** A watcher trace showing the same path emitted twice producing two imports.

**Would refute:** Watcher debounce / seen-set (Issue #94 fixed double-subscription) prevents
re-emission. Primary mechanism remains "re-import of previously-processed audio".

## Source Code Trace

| Element       | Detail                                                                                              |
| ------------- | --------------------------------------------------------------------------------------------------- |
| Error origin  | `dashboard/src/stores/importQueueStore.ts:303-329` — `processSessionJob` dedup gate (blocking await) |
| Trigger       | Folder Watch enqueues `session-auto` jobs (`importQueueStore.ts:702`); `/import` returns non-empty `dedup_matches` for re-imported audio (`transcription.py:1247-1261,1301`) |
| Condition     | Imported file's `audio_hash` or `normalized_audio_hash` equals a prior `transcription_jobs`/`recordings` row |
| Related files | `dedupChoiceStore.ts`, `DedupChoiceContainer.tsx`, `DedupPromptModal.tsx`, `App.tsx:821`, `client.ts:830`, `types.ts:104`, `dedup_query.py`, `job_repository.py`, `database.py` |

## Conclusion

**Confidence: High.** The issue described in GH #120 is **still present** in the current code. The
"Possible duplicate detected" modal still fires for Folder Watch (`session-auto`) jobs exactly as for
manual imports, blocking the serial import queue until a human responds. There is **no** auto-resolve
mode, job-type branch, setting, config key, or env var anywhere that lets a batch run unattended.
Five independent adversarial lenses each tried and failed to refute this. The bug is confined to the
**session import surface**; notebook auto-watch (`processNotebookJob`) is unaffected (it never reads
`dedup_matches`).

## Recommended Next Steps

### Fix direction (investigation stops at diagnosis; this is guidance, not an implementation)

Introduce an **unattended duplicate policy** for auto/batch jobs. Minimal, well-scoped options:

1. **Job-type branch (smallest fix).** In `processSessionJob`, when `job.type === 'session-auto'`,
   resolve duplicates without the modal — default to `create_new` (preserves the data-loss-averse
   invariant: never silently drop a transcription). One-branch change at `importQueueStore.ts:303`.
2. **Policy setting (better UX).** Add `folderWatch.duplicatePolicy: 'ask' | 'create_new' | 'skip'`
   to the config/Electron defaults and `SettingsModal`. `session-auto` jobs read it and bypass the
   modal accordingly; `session-normal` keeps `ask`. Wire through `dedupChoiceStore` (add an
   auto-resolve path) or short-circuit before `requestChoice`.
3. **(Optional) "Don't ask again this batch"** checkbox on the modal that persists a session-scoped
   choice — complements either option above.

Add tests asserting `session-auto` jobs do **not** block on the modal (the gap Finding 6 identified).

### Secondary (user's "how do I delete existing recordings?" question)

That is a usage question, not a code fix: existing transcripts/recordings can be removed via the
dashboard's notebook/session management UI (or by clearing the durability rows). Worth a short doc
note, but it does not resolve the blocking-prompt defect.

## Reproduction Plan

1. Transcribe a file via session import (manual or Folder Watch) so a `transcription_jobs` row with
   `audio_hash` is persisted.
2. Enable Folder Watch on a session folder; drop the **same** audio file (or a different container of
   identical audio) into it.
3. Expected (bug): the "Possible duplicate detected" modal appears and the import queue halts until a
   manual choice — unattended batch is impossible.
4. Verify fix: with the policy/branch in place, the `session-auto` job auto-resolves (default: creates
   a new entry) and the queue advances with no modal.

## Side Findings

- `dashboard/src/api/client.ts:785` — `dedupCheck` (the standalone `POST /import/dedup-check`
  pre-flight endpoint) is **dead code**; nothing in the dashboard calls it. The team built a
  pre-flight path but shipped only the inline `dedup_matches` flow. (Evidence-graded: Confirmed.)
- Notebook auto-watch is unaffected — `processNotebookJob` (`importQueueStore.ts:369-408`) never reads
  `dedup_matches` and the notebook upload endpoint does not populate it (`types.ts:200-204`).
- Backend hash compute is wrapped in try/except that silently NULLs hashes on failure
  (`transcription.py:1218-1231`) — a failure mode that *coincidentally* suppresses dedup, not a
  sanctioned batch mode.

## Follow-up: 2026-06-26 — Fix implemented (TDD)

**Resolution.** Added an unattended duplicate policy so Folder Watch (`session-auto`) imports no
longer block the queue on the interactive modal.

- `dashboard/src/stores/importQueueStore.ts` — new `DuplicatePolicy` (`'ask' | 'create_new'`) +
  `resolveDuplicateChoice(jobType, matches)`; `processSessionJob` now calls it instead of always
  awaiting `requestChoice`. `session-auto` only prompts when policy is `'ask'`; every other case
  (the `'create_new'` default, an unknown/legacy value, or an IPC read failure) creates a new entry
  — so a corrupt config can never re-block the queue (would re-introduce #120) or skip a file.
- `dashboard/electron/main.ts` — `folderWatch.duplicatePolicy` default `'create_new'`.
- `dashboard/components/views/SettingsModal.tsx` — Settings → App → "Folder Watch" dropdown
  (Always create a new entry / Ask each time), load+save wiring, load-time value normalization.
- `dashboard/src/stores/importQueueStore.test.ts` — 6 TDD tests (RED→GREEN).

**`'skip'` deliberately NOT shipped.** A code review flagged that `'skip'`→`'use_existing'` could
lose data. Verified the cause: `_run_file_import` (`transcription.py:840-843`) "does NOT save to
database" — import durability rows stay `status='processing'` with `result_text=NULL` forever
(results live only in the in-memory `job_tracker`). So a session-import dedup match is a bare
hash anchor with **no retrievable transcript**, and the reviewer's proposed `status='completed'`
filter would have *excluded all import rows* and broken session dedup. The safe resolution was to
drop `'skip'` (only `'ask'`/`'create_new'`, both data-loss-safe) rather than build disk
verification. Legacy `'skip'` values stored by no build are coerced to `'create_new'`.

**Verification.** 1440/1440 frontend tests pass; typecheck (app + electron) + eslint clean.
UI-contract drift (`ServerView` classes, pre-existing on main, unrelated) handled as a separate
commit. **Status: Concluded — fixed on branch `fix/gh120-folder-watch-dedup-policy`.**
