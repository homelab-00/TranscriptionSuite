---
title: 'Sprint 2 carve-out — DedupPromptModal full choice-flow integration'
type: 'feature'
created: '2026-05-04'
status: 'done'
baseline_commit: '6d7fffb'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sprint 2 ships `DedupPromptModal` (component-tested in isolation) and plumbs `dedup_matches` from `/api/transcribe/import` through `apiClient` into `importQueueStore`. The current integration surfaces duplicates only as a one-line toast — the full AC2.4.AC2 modal-with-choices flow ("Use existing" / "Create new") never mounts because no caller renders the modal or awaits a user decision before the queue advances.

**Approach:** Add a small Zustand store (`useDedupChoiceStore`) that holds at most one pending decision. Mount a top-level `DedupChoiceContainer` in `App.tsx` that subscribes to the store and renders `DedupPromptModal`. In `importQueueStore.processSessionJob`, when `dedup_matches` is non-empty, call `requestChoice(matches)` which returns a `Promise<DedupChoice>`. The queue iteration awaits the promise and routes on the resolution: `'use_existing'` → cancel the just-started server job, mark this queue entry done (no output written), ARIA-announce; `'create_new'` → continue the existing happy-path flow; `'cancel'`/Esc → same as `'use_existing'` (the user clearly does not want a duplicate).

## Boundaries & Constraints

**Always:**
- The modal is presentational; routing logic lives in the caller (already the contract per the existing component file's docstring).
- "Use existing" cancels the server job via the existing `apiClient.cancelTranscription()` call. Do not invent a new cancel path.
- The pending-choice promise MUST resolve exactly once per request — no double-resolve, no leak. The store enforces this internally.
- Queue iteration cannot proceed past a job awaiting a decision. Other concurrency (e.g. starting a fresh enqueue) must not bypass the decision.
- ARIA announcements use the existing `useAriaAnnouncer` infrastructure (Story 1.8). New announcements must include the duplicate's display name.

**Ask First:**
- If "Use existing" needs to navigate to the prior recording (vs just cancelling the new one), ASK the user. Default for v1: cancel-only. Navigation requires choosing between session/notebook tab and is product-design work outside this carve-out.

**Never:**
- Do NOT change `DedupPromptModal`'s prop shape or rendering. Sprint 2 already passed its component tests.
- Do NOT change the server's `dedup_matches` response shape. Items 2 + 3 already extended it; Item 4 is purely consumer-side.
- Do NOT block the WHOLE queue if multiple concurrent enqueues land matches. The decision is per-job; the queue serializes naturally.
- Do NOT add a "remember my choice" persistence layer. Each upload is its own decision.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Import response has empty `dedup_matches` | Normal happy-path import | Queue continues to writing phase as today; no modal | N/A |
| Import response has matches; user clicks "Create new" | User chooses to proceed | Queue continues to writing phase; final job marked `success` | N/A |
| Import response has matches; user clicks "Use existing" | User chooses to dedup | `apiClient.cancelTranscription()` fires; queue entry removed (or marked `cancelled`); ARIA-announce "duplicate skipped"; queue advances to next pending job | If cancel API errors: still mark the queue entry skipped (best-effort cancel) |
| User presses Escape on the modal | Same effect as "Use existing" | Identical behavior to clicking "Use existing" | N/A |
| Server rejects cancel (e.g. job already finished) | Cancel API returns non-200 | Treat as best-effort: still skip the local queue entry; log warn | N/A |
| Multiple matches in `dedup_matches[]` | Modal opens with first match (existing component contract) | Single decision applies to the current job (same as Sprint 2 toast behavior) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/stores/dedupChoiceStore.ts` -- NEW: Zustand store holding the active pending decision and a `requestChoice(matches): Promise<DedupChoice>` action.
- `dashboard/components/import/DedupChoiceContainer.tsx` -- NEW: subscribes to the store, renders `DedupPromptModal`, wires choice → resolve.
- `dashboard/App.tsx` -- mount `<DedupChoiceContainer />` near other top-level modals.
- `dashboard/src/stores/importQueueStore.ts` -- in `processSessionJob`: replace toast-only dedup branch with `await requestDedupChoice(matches)`, branch on result. The notebook upload endpoint (`/api/notebook/transcribe/upload`) does not currently return `dedup_matches` in its response — the dashboard's notebook path remains unchanged for now (notebook-side hash WRITES land via Item 2; future sprints can add a pre-flight dedup-check or extend the notebook response).
- `dashboard/src/api/types.ts` -- add optional `source?: 'transcription_job' | 'recording'` field on `DedupMatch` (matches the new server field).
- `dashboard/src/stores/__tests__/dedupChoiceStore.test.ts` -- NEW: store unit tests (single pending decision invariant, resolve-once, cancel resets state).
- `dashboard/components/import/__tests__/DedupChoiceContainer.test.tsx` -- NEW: container test (renders modal when store has pending; choice → resolves promise).

## Tasks & Acceptance

**Execution:**
- [ ] `dashboard/src/stores/dedupChoiceStore.ts` -- new Zustand store + `requestChoice` action returning a Promise.
- [ ] `dashboard/components/import/DedupChoiceContainer.tsx` -- new mount component.
- [ ] `dashboard/App.tsx` -- render `<DedupChoiceContainer />`.
- [ ] `dashboard/src/stores/importQueueStore.ts` -- await dedup choice in `processSessionJob` and `processNotebookJob`; route on result.
- [ ] `dashboard/src/api/types.ts` -- add optional `source` field on `DedupMatch`.
- [ ] `dashboard/src/stores/__tests__/dedupChoiceStore.test.ts` -- new test file.
- [ ] `dashboard/components/import/__tests__/DedupChoiceContainer.test.tsx` -- new test file.
- [ ] `_bmad-output/implementation-artifacts/deferred-work.md` -- DELETE the no.4 entry.
- [ ] `dashboard` UI contract — run `npm run ui:contract:check` after edits per CLAUDE.md.

**Acceptance Criteria:**
- Given a fresh state with no pending decision, when `requestChoice([match])` is called, then the store updates `pendingMatches` and the returned promise stays unresolved until a choice is made.
- Given a pending decision, when `resolve('use_existing')` is called, then the original promise resolves to `'use_existing'` and `pendingMatches` is cleared.
- Given the container is mounted with no pending decision, when rendered, then no modal is in the DOM.
- Given `dedup_matches` is non-empty in an import response, when `processSessionJob` runs, then it awaits the user's choice before continuing.
- Given the user picks "Use existing", when the choice resolves, then `apiClient.cancelTranscription()` is called and the job is not marked `success`.
- Given the user picks "Create new", when the choice resolves, then the queue continues to the writing phase as before.
- Given Vitest runs (`npm test`), then all new tests pass and existing dedup tests do not regress.

## Spec Change Log

## Verification

**Commands:**
- `cd dashboard && npm test -- --run dedup` -- expected: all dedup-related tests pass.
- `cd dashboard && npm run typecheck` -- expected: no errors.
- `cd dashboard && npm run ui:contract:check` -- expected: contract baseline holds (or update + re-run per CLAUDE.md).

**Manual checks:**
- Import the same audio file twice via the dashboard. On the second import, the modal must appear with the prior recording's name. Click "Create new" → import proceeds. Click "Use existing" → import cancels, queue advances. Press Escape → identical to "Use existing".
