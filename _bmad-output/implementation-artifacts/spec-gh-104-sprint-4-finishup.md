---
title: 'Sprint 4 finish-up — wire deferred items 1–4 from Issue #104'
type: 'chore'
created: '2026-05-04'
status: 'in-review'
baseline_commit: 'a237b186d6ca94e382780ccfae029f5d2c9e5e24'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/sprint-4-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sprint 4 commits A–H landed Stories 6.1–6.11 (auto-actions coordinator, sweeper, retry, escalation), but four small finish-up items were scoped out to keep the LOC budget under 4000. The result: the sweeper exists but never runs (lifespan not wired); auto-actions don't fire from dashboard uploads (`profile_id` never sent); even when they fire, the user can't see them (`AutoActionStatusBadge` not rendered in `AudioNoteModal`); and the diarization-review keyboard contract advertises ←/→ attribution-cycling but the handler body is empty.

**Approach:** One bundled finish-up spec covering all four cleanups as separate atomic commits on `gh-104-sprint-4`. Each item lands with a concrete defense shape already pre-decided in the deferred-work file — no new architectural decisions, just wiring the pieces that were already built.

## Boundaries & Constraints

**Always:**
- The lifespan sweeper task must be cancel-safe (mirror the `audio_cleanup` `try/except CancelledError` pattern at `api/main.py:600-606`).
- Sweeper interval must be configurable via `auto_actions.deferred_export_sweep_interval_s` (default 30.0s), so tests can override to a tiny interval.
- Profile-snapshot column on `recordings` (`auto_action_profile_snapshot`, migration 015) is the row of record — the dashboard sends the *id*, the backend persists the *snapshot*. Don't reroute that.
- Recording-detail response must surface `auto_summary_status`, `auto_summary_error`, `auto_export_status`, `auto_export_error`, `auto_export_path` so the badge can render without a second round-trip.
- ←/→ key handling must NOT change `aria-activedescendant` (the existing keyboard-contract test at `DiarizationReviewView.keyboard.test.tsx:186-201` asserts this — keep it green).
- `alternative_speakers` is the set of distinct `speaker_id`s in the recording minus the turn's current speaker, ordered by first-appearance index. No pyannote re-analysis.

**Ask First:**
- If `recordings.SELECT *` doesn't already expose the new auto-action columns to `get_recording_detail` because of a row-factory or schema drift, HALT before adding manual column projection — that suggests a deeper migration issue.
- If the sweeper interval config read shape diverges from `durability_config.get("cleanup_interval_hours", 24)` style at `api/main.py:456`, HALT and ask which shape to use.

**Never:**
- Don't change `auto_action_sweeper.periodic_deferred_export_sweep` itself. It's tested and shipped — only wire it.
- Don't extend the manual-retry endpoint contract.
- Don't introduce a new "active profile" hook — `useActiveProfileStore` already exists and `NotebookView` already consumes it (line 267).
- Don't build a similarity-score backend for `alternative_speakers`. Appearance order is fine per deferred-work guidance.
- Don't refactor `AudioNoteModal.tsx` beyond adding the badge render block.
- Don't touch the folder-watch `handleFilesDetected` path — that's its own deferred item if needed.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sweeper boots | Server starts, `auto_actions.deferred_export_sweep_interval_s=0.05`, one row at `auto_export_status='deferred'` with destination dir present | Within ~0.2s, status flips to `success` | If sweeper raises, log + continue (existing pattern) |
| Sweeper cancellation | Server shuts down with sweeper running | Task cancelled cleanly, no `Task was destroyed but it is pending` warning | `asyncio.CancelledError` is the clean exit |
| Upload with profile | NotebookView upload, `useActiveProfileStore.activeProfileId=7` | FormData includes `profile_id=7`, backend `_run_transcription` receives the snapshot | profile_id missing → existing behavior (no auto-actions, no error) |
| Upload without active profile | `activeProfileId=null` | FormData omits `profile_id` (don't send `null` or `'null'`) | N/A |
| Badge render — success | `recording.auto_summary_status='success'` | Green StatusLight, "Summary ready", no retry button | N/A |
| Badge render — failed | `recording.auto_summary_status='failed'`, `auto_summary_error='LLM timeout'` | Red StatusLight, "Summary failed: LLM timeout", retry button visible | onRetry → useAutoActionRetry mutation |
| Badge — null status | `auto_summary_status=null` | `statusToBadgeProps` returns null → badge not rendered | N/A |
| ←/→ with alternatives | Active turn has `alternative_speakers=['SPK_01','SPK_02']`, current `speaker_id='SPK_00'` | → cycles index 0→1→2 (max length-1); ← cycles back to 0 | If alternatives empty, keys still preventDefault but don't move |
| ←/→ no alternatives | Single-speaker recording (only `SPK_00` ever) | `alternative_speakers=[]`; keys are no-op (still consumed) | aria-activedescendant unchanged |
| Accept after cycling | User pressed → twice, then Enter | Decision payload's `speaker_id` = `alternative_speakers[1]`, decision='accept' | N/A |

</frozen-after-approval>

## Code Map

- `server/backend/api/main.py:447-462,600-614` -- lifespan create_task + cancel pattern (mirror)
- `server/backend/core/auto_action_sweeper.py:34` -- `periodic_deferred_export_sweep(interval_s)` to schedule
- `server/backend/api/routes/notebook.py:86-141,200-217,476-498` -- RecordingResponse, RecordingDetailResponse, get_recording_detail, DiarizationConfidenceResponse, get_diarization_confidence
- `server/backend/core/diarization_confidence.py:39-84` -- `per_turn_confidence` — extend to compute alternative_speakers
- `dashboard/components/views/NotebookView.tsx:267,1695-1702` -- `activeProfileId`, manual upload `addFiles` call
- `dashboard/components/views/AudioNoteModal.tsx:430,757-811` -- `activeProfileId` already imported; summary panel insertion area
- `dashboard/components/recording/AutoActionStatusBadge.tsx:75,147` -- AutoActionStatusBadge + statusToBadgeProps (consume)
- `dashboard/src/hooks/useAutoActionRetry.ts:26` -- `useAutoActionRetry(recordingId)` (consume)
- `dashboard/src/api/types.ts:143-161` -- `Recording` / `RecordingDetail` interfaces — extend
- `dashboard/src/utils/diarizationReviewFilter.ts:13-18` -- `ReviewTurn` interface — extend with `alternative_speakers?`
- `dashboard/components/recording/DiarizationReviewView.tsx:41-45,108-124,179-185` -- decision shape, recordDecision, the empty key body
- `dashboard/components/recording/__tests__/DiarizationReviewView.keyboard.test.tsx:186-201` -- existing test stays green

## Tasks & Acceptance

**Execution:**

*Commit 1 — sweeper lifespan wiring (Sprint 4 no. 1)*
- [x] `server/backend/api/main.py` -- in `lifespan`, after the audio_cleanup block, read `auto_actions.deferred_export_sweep_interval_s` from `config.config`, `asyncio.create_task(periodic_deferred_export_sweep(interval_s))`, store handle, cancel + await on shutdown alongside the other cleanup tasks.
- [x] `server/backend/tests/test_main_lifespan_sweeper.py` (new) -- async test that drives the lifespan with a tiny interval (e.g. 0.05s), inserts a `deferred` row + creates the destination dir, awaits ~0.2s, asserts `auto_export_status='success'`. Patch `LLMClient`/external bits as needed.

*Commit 2 — dashboard sends profile_id (Sprint 4 no. 2)*
- [x] `dashboard/components/views/NotebookView.tsx` -- in the manual notebook-upload `addFiles` call (~line 1695), pass `profile_id: activeProfileId ?? undefined` so a null pointer doesn't end up in FormData.
- [x] `dashboard/components/__tests__/NotebookView.profile-id.test.tsx` (new) -- mount NotebookView with `useActiveProfileStore` set to a known id, mock `apiClient.uploadAndTranscribe`, trigger an upload, assert the second-arg options carry `profile_id`. Add a paired test for `activeProfileId=null` → options.profile_id === undefined.

*Commit 3 — recording-detail surfaces auto-action status + badge renders in AudioNoteModal (Sprint 4 no. 3)*
- [x] `server/backend/api/routes/notebook.py` -- extend `RecordingResponse` with the five auto-action fields (status, error for both; plus `auto_export_path`); `RecordingDetailResponse` inherits them automatically. `get_recording_detail` already passes `**recording`, so the row-as-dict already carries them — no projection change needed.
- [x] `server/backend/tests/test_recording_detail_auto_action_fields.py` (new) -- write a recording row with auto_summary_status='success', auto_export_status='deferred', call get_recording_detail directly per CLAUDE.md route-test pattern, assert all five fields appear in the JSON response.
- [x] `dashboard/src/api/types.ts` -- add `auto_summary_status: string | null`, `auto_summary_error: string | null`, `auto_export_status: string | null`, `auto_export_error: string | null`, `auto_export_path: string | null` to `Recording` interface.
- [x] `dashboard/components/views/AudioNoteModal.tsx` -- import `AutoActionStatusBadge` + `statusToBadgeProps` + `useAutoActionRetry`. Inside the summary panel area (near the existing summary block, anchored on `recording`), compute summaryProps/exportProps via statusToBadgeProps, render two badges when not null, wire `onRetry` to `retry.mutate`. Use existing Tailwind utility classes only (no new className tokens) to avoid a UI-contract update.
- [x] `dashboard/components/views/__tests__/AudioNoteModal.auto-actions.test.tsx` (new) -- render the modal with a stubbed `useRecording` returning recording with auto_summary_status='success' + auto_export_status='failed', assert two badges render, assert clicking the export retry button calls the retry endpoint via the hook.

*Commit 4 — diarization-review attribution cycling (Sprint 4 no. 4)*
- [x] `server/backend/core/diarization_confidence.py` -- before the per-turn loop, scan all segments to build `appearance_order: list[str]` of distinct non-null speaker_ids in first-seen order. Each emitted turn gets `alternative_speakers = [s for s in appearance_order if s != current_speaker_id]`.
- [x] `server/backend/api/routes/notebook.py` -- extend `TurnConfidence` with `alternative_speakers: list[str] = []` (default [] keeps response shape backward-compat for serialized clients).
- [x] `server/backend/tests/test_diarization_confidence.py` -- add a case with 3 distinct speakers; assert each turn's `alternative_speakers` excludes the current speaker and preserves appearance order.
- [x] `dashboard/src/utils/diarizationReviewFilter.ts` -- add `alternative_speakers?: string[]` to `ReviewTurn`.
- [x] `dashboard/components/recording/DiarizationReviewView.tsx` -- add `attributionIndexByTurn: Map<number, number>` state. ←/→ updates `attributionIndexByTurn[currentTurnIndex]` clamped to `[0, alternative_speakers.length - 1]`; reset to 0 when `activeIndex` changes. The current attribution = `turn.alternative_speakers?.[idx] ?? turn.speaker_id`. `recordDecision('accept', …)` reads the current attribution from the map and writes it to `speaker_id` in the decision payload (so an Enter after cycling persists the chosen speaker, not the original). Announce the cycled speaker via `useAriaAnnouncer`.
- [x] `dashboard/components/recording/__tests__/DiarizationReviewView.keyboard.test.tsx` -- add: ArrowRight cycles to next alternative; ArrowLeft cycles back; ArrowRight does NOT change aria-activedescendant (regression of existing case); accept-after-cycle puts the chosen speaker into the decision payload.

**Acceptance Criteria:**
- Given a server boot with one deferred-export row whose destination becomes available, when the sweeper interval elapses, then `auto_export_status` flips to `success` without a manual retry call.
- Given a NotebookView upload with `activeProfileId=7`, when the upload kicks off, then the FormData contains `profile_id=7` and `_run_transcription` receives a non-empty `profile_snapshot`.
- Given a recording with `auto_summary_status='success'` and `auto_export_status='failed'`, when `AudioNoteModal` opens, then two `AutoActionStatusBadge` components render with the correct severities and the export badge has a working retry button.
- Given a turn under review with two alternative speakers, when the user presses → twice and then Enter, then the decision payload's `speaker_id` equals the second alternative and `aria-activedescendant` did not change during the ←/→ presses.
- Given the existing keyboard-contract test ("←/→ are consumed but don't advance selection"), the test still passes (no regression in single-speaker recordings).

## Verification

**Commands:**
- `cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short` -- expected: all green, including new `test_main_lifespan_sweeper.py`, `test_recording_detail_auto_action_fields.py`, and the extended `test_diarization_confidence.py`.
- `cd dashboard && npm test -- --run` -- expected: all Vitest green, including new `NotebookView.profile-id.test.tsx`, `AudioNoteModal.auto-actions.test.tsx`, and extended `DiarizationReviewView.keyboard.test.tsx`.
- `cd dashboard && npm run ui:contract:check` -- expected: pass without baseline-update (badge uses existing classes; if new className tokens are introduced, run the full update sequence per CLAUDE.md).
- `cd dashboard && npm run typecheck` -- expected: clean.

**Manual checks:**
- After commit 1, grep `api/main.py` for `periodic_deferred_export_sweep` and confirm both `create_task` and `cancel/await` blocks are present.
- After all commits, delete the four entries (Sprint 4 no. 1, 2, 3, 4) from `_bmad-output/implementation-artifacts/deferred-work.md` per its own header rule ("When an item ships, delete the entry").
