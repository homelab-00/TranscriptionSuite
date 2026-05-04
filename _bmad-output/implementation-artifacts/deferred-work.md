# Deferred Work

## Triage Rule

Before appending an item to this file, it must clear **all** of:

1. **Severity is MEDIUM or higher** — user-visible symptom, not a latent/theoretical hazard.
2. **Not pre-existing** — caused by the sprint under review, or surfaced a symptom the sprint was meant to close but didn't.
3. **Not already owned by a named future milestone** (M6/M7/a11y sweep/etc.) — if it has an owner, track it there, not here.
4. **Defense shape is concrete** — not "if a real user complains" or "when telemetry lands."

If any check fails, **do not append**. Close the concern in-review or drop it.

LOW-severity items, "pre-existing" hazards, TOCTOU races requiring deliberate mutation, test-coverage gaps for un-bugged branches, and cosmetic polish do **not** belong here.

When an item ships, **delete the entry** — git history + the spec file are the durable record. This file is the active queue, not a changelog.

---

## Active Items

### gh-86 no. 2 — Pyannote diarization fails on Mac M4Pro Metal bare-metal (MEDIUM)

**Symptom (reported 2026-04-19, Issue #86 item 2):** On Mac M4Pro, Metal mode, model `mlx-community/parakeet-tdt-0.6b-v3`, importing a file and transcribing with **Sortformer (Metal)** diarization works; switching to **Pyannote (`pyannote-speaker-diarization-community-1`)** does NOT work. HF token is set with fine-grained access for the gated repo and access has been granted on the model page. Reporter says logs are also empty (the empty-log issue was split off as Goal A and shipped via `spec-gh-86-mlx-log-pipeline-gaps.md`).

**Why deferred (split per Quick Dev workflow 2026-04-26):**
1. Independently shippable from the Goal A "record button disabled" fix — different code path entirely (server-side STT + diarization wiring vs. dashboard renderer gate).
2. Severity is MEDIUM — user-visible (one of two diarizer choices flat-out fails on a supported platform), but a working alternative (Sortformer) exists, so not blocker.
3. Not pre-existing — actively reported against latest DMG (v1.3.3).
4. No named milestone owner.
5. Defense shape is concrete — investigation must answer: does pyannote's PyTorch model load on Apple Silicon bare-metal at all? What device does the diarizer pick (MPS / CPU)? Does the failure show in the server logs (now visible after Goal A shipped)?

**Investigation needed before fix:**
- Read `server/backend/core/diarization/` (or wherever pyannote is wired) — confirm device selection logic for Apple Silicon bare-metal (no CUDA, MPS or CPU fallback).
- Check whether `pyannote.audio 4.0.4` is even installed on the bare-metal Apple Silicon path — the `mlx` extra is mutually exclusive with `whisper`/`nemo`/`vibevoice_asr` extras (see `[tool.uv] conflicts`); is pyannote bundled in the MLX extra or separately?
- Cross-reference the `apple-silicon-mlx` label hits in recent issues for a pattern — is pyannote-on-MPS a known-broken combination?

**Fix sketch (post-investigation):** Three plausible shapes — (a) pyannote dependency missing from the MLX extra path → add it or document the limitation in UI; (b) device-selection bug forcing CUDA on Apple Silicon → add MPS/CPU fallback; (c) pyannote.audio + Apple Silicon MPS is genuinely broken upstream → gate the pyannote choice with a "Linux/Windows + CUDA only" capability flag and surface a clear "use Sortformer on Mac" message in the dashboard. Choice depends on investigation outcome.

### gh-87 Wave 4 — design-conversation blur reductions (CONDITIONAL)

**User-directed entry (2026-04-25):** Severity is LOW per triage rule (these are *additional GPU headroom*, not user-visible bugs once W1–W3 ship). **Retained on the shelf per explicit user instruction during the 2026-04-25 brainstorming-session extension.** Single bundled pointer entry — full per-action detail lives in `_bmad-output/brainstorming/brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md` (Phase 4, Wave 4).

**Status note (updated 2026-04-26):** E125 (user-facing toggle) shipped in commit `f138b37` — `Settings → App → Appearance → Blur effects`, default ON, OFF persisted via `ui.blurEffectsEnabled`. The E126 default-shift decision (default `--glass-fidelity: 0.5` vs `1.0`) remains in Wave 4 here, and is now the next-most-likely lever if reporter feedback says "I did not know about the toggle". Companion Cluster 1 follow-up (idle visualizer character restoration via CSS/SVG keyframes) shipped in commit `a129877`.

**Trigger #2 status (2026-04-26):** Issue #91 (Glitch scrolling Model Selection — Mac, darwin 15.7.5) was filed 2026-04-23 — technically satisfies trigger condition 2. However, with E125 now shipped, #91 is addressable via the user-facing opt-out. Re-triage when reporter confirms whether the toggle resolves the symptom; if not, promote E126 (default-shift) next.

**Trigger conditions (any one):**
1. Wave 3's native vibrancy + radius token does NOT close issue #87 — Mac reporter still sees idle CPU > 2% or GPU helper > 1%.
2. A new Mac/Windows GPU-related issue is filed against the dashboard.
3. Project owner decides to formalize the blur-tier design language proactively (e.g. ahead of a wider redesign).

**Wave 4 candidate set (do not implement until trigger fires):**
- **E89** — Designer audit: walk every `backdrop-blur` site, classify T1/T2/T3/T4 per the tier vocabulary shipped in F1.
- **E126** — Default `--glass-fidelity: 0.5` (E125 toggle now in active sprint). Decision required: ship reduced default or full default?
- **E48 / E74 / E127** — Pre-rendered blurred PNGs per theme. Decision required: accept build-time blur philosophy?
- **E31 / E32** — Confine blur to chrome only / frosted-edge only. Decision required: major aesthetic shift accepted?
- **E59 / E92** — Platform-asymmetric glass quality (Mac full glass, Linux/Windows tinted-only). Decision required: accept platform parity loss?

**Re-triage:** when W3 ships, re-evaluate this entry. If issue #87 closes, drop. If still open, promote individual candidates to active sprint work.

### gh-102-followup carve-out no. 2 — Folder-watch auto-imports drop `session.mainLanguage` (MEDIUM)

**Surfaced 2026-04-30 during gh-102-followup planning.** `dashboard/src/stores/importQueueStore.ts::handleFilesDetected` (~L580-602) snapshots `sessionConfig` / `notebookConfig` for auto-watch jobs but the snapshot does not include the user's persisted Source Language. Auto-imported files inherit the same gh-81 `ValueError` on Canary that the manual flow does.

**Why deferred (split off from the gh-102-followup spec at user request):** Different trigger surface (filesystem watcher, not user-initiated drop). Adds an additional async-loading race to design around (see "Defense shape" below). Not in the reporter's reproduction.

**Defense shape (concrete, decided 2026-04-30):** When `useLanguages.loading === true` (no real server data yet), **pause folder-watch detection entirely** — do not enqueue any file. The pause clears automatically when the languages query resolves and the resolve guard becomes accurate. Implementation outline:
1. Extend `SessionConfig` / `NotebookConfig` types in `importQueueStore.ts` with `language: string | undefined` (raw display name) so the picker selection can be snapshotted by the syncing `useEffect` in `SessionImportTab` / notebook tab.
2. In `handleFilesDetected`: read the languages list (via a dedicated store-level cache populated by `apiClient.getLanguages()` once the languages-query resolves elsewhere); resolve the snapshotted display name to a code; if no real languages data is available yet, drop the detected batch with a warn-level `appendWatchLog` entry and a toast ("Folder Watch paused — languages still loading"). Reuse the existing `watcherServerConnected` pause-style flow.
3. When Canary is active and the resolve fails (picker unset / `Auto Detect`), drop the batch with a clear `appendWatchLog` warn ("Folder Watch paused — Source Language required for the active model").

**Re-triage trigger:** ship when the next folder-watch sprint touches `importQueueStore.ts`, or when a Canary user reports auto-watch failures.

### gh-101 — `hasVulkanWsl2SidecarImage` does not detect partial-pull / corrupted-layer images (LOW-MEDIUM)

**Surfaced 2026-05-02 during code review of `spec-gh-101-followup-vulkan-wsl2-comprehensive`.** `docker image inspect` returns success for an image with corrupted layers from a partial pull. Compose `up` then fails much later with an opaque whisper-server error pointing at missing files inside the container, far from the dashboard's preflight check.

**Defense shape:** Run a `docker run --rm <image> /bin/true` smoke test (or check `RepoDigests.length > 0`) after the inspect. Defer because corrupted partial pulls require an interrupted `docker pull` and the Dockerfile build path doesn't pull in pieces — for v1.3.5 every Vulkan-WSL2 user builds locally, so the failure mode is already low-likelihood.

**Re-triage trigger:** First user report of "vulkan-wsl2 starts but whisper-server crashes immediately" OR when the WSL2 sidecar gets a published GHCR tag and users start pulling it (no longer "every user builds locally").

---

## Sprint 1 (Issue #104, Audio Notebook QoL pack — epic-foundations + epic-model-profiles)

Sprint 1 landed Stories 1.2–1.9 + 8.1–8.4 (12 stories) on `gh-104-prd`.
Items 1–5 were closed in the Sprint 1 deferred-items follow-up commit
(2026-05-03) — see git history for the actual integration. Only the
explicit Sprint 3 placeholder remains.

### 1. F1 + F4 race-guard implementation (Story 6.11 dependency)

**What:** Sprint 1 prepared the data substrate (profile snapshot column,
review-state table) but did NOT implement the F1↔F4 cross-feature race
guard. That belongs to Story 6.11 (Sprint 3 / epic-auto-actions).

**Why deferred:** Out of scope per epics.md — flagged here so the Sprint 3
implementer doesn't assume the guard is already in place.

**Re-triage trigger:** Sprint 3 kickoff.

---

## Sprint 3 (Issue #104, Audio Notebook QoL pack — epic-aliases-mvp + epic-aliases-growth)

Sprint 3 landed Stories 4.1–4.5 + 5.1–5.9 (14 stories) on `gh-104-prd`.
Two items are explicitly carried forward.

### 1. Longform/import diarization-completion hook for Story 5.6 trigger

**Surfaced 2026-05-04 during sprint-3-design pass.** Sprint 3 wired
`on_transcription_complete()` into the **notebook upload** completion
path only (the path that exercises diarization in the J4 reviewer
journey — researcher uploads a recording, opens the detail view, sees
the banner). The two other transcription-completion sites — longform
(`transcription.py` durability worker) and direct-import (`/import`
in-memory job_tracker) — do not yet fire the trigger.

**Why deferred:** The longform/import completion lifecycle is owned by
the Sprint 4 auto-summary worker (Story 6.2). Wiring the trigger into
that worker AND the upload path in Sprint 3 would have duplicated the
call site; the Sprint 4 design will pick the right single owner.

**Reconfirmed-deferred note (2026-05-04):** Investigated under the
`/bmad-quick-dev` Sprint 3 carry-forward pass. Re-confirmed deferral on
a structural ground: `recording_diarization_review` is FK'd to
`recordings(id)` (migration 010), and **neither `transcription.py` nor
`/import` produces a `recordings` row** — the `/import` docstring
(transcription.py:1130) explicitly notes *"this does NOT save to the
database"* (i.e. the `recordings` table); the durability row written by
`/import` lives in `transcription_jobs` and exists *"purely so the
dedup-check endpoint can find re-imports"*. Without a `recording_id`,
`on_transcription_complete(recording_id, …)` cannot run from those
paths. The only ways to wire this now are: (a) auto-promote
`transcription_jobs` rows to `recordings` rows on completion (large new
feature, Sprint-4-sized scope); (b) re-key the lifecycle table by
`job_id` (data migration + repository rewrite); (c) add a no-op stub
that future work would have to refactor. None are cheap. Sprint 4
Story 6.2 is expected to introduce the unified completion lifecycle
that resolves this — keep the trigger here until then.

**Defense shape (concrete):** When Story 6.2 lands the auto-summary
lifecycle, add a single hook just before the auto-summary fires:

```python
# Sprint 4 — pseudocode for the call site
from server.core.diarization_review_lifecycle import (
    on_transcription_complete, auto_summary_is_held,
)
on_transcription_complete(recording_id, has_low_confidence_turn=...)
if auto_summary_is_held(recording_id):
    return  # banner asks user to review first
```

**Re-triage trigger:** Sprint 4 Story 6.2 kickoff.

---

### Sprint 4 no. 1 — Auto-action sweeper not wired into FastAPI lifespan (MEDIUM)

**Symptom:** `server/backend/core/auto_action_sweeper.py::periodic_deferred_export_sweep` is implemented and unit-tested (cancel-safe, bootstrap-safe per NFR24a), but `server/backend/main.py`'s `lifespan` async-generator does NOT start it. Production servers will never sweep `auto_export_status='deferred'` rows back to `success` when the destination comes online, defeating Story 6.8 / R-EL12 entirely. The user-visible failure mode is identical to "auto-export is silently broken" once the destination remounts.

**Why deferred:** Sprint 4 commits A–H landed before lifespan wiring; the omission was caught during sprint-completion review. Caused by Sprint 4, no upstream owner.

**Defense shape:**

```python
# server/backend/main.py — inside lifespan async-generator, alongside audio_cleanup
from server.core.auto_action_sweeper import periodic_deferred_export_sweep
sweep_interval = config.get("auto_actions", "deferred_export_sweep_interval_s", default=30.0)
sweep_task = asyncio.create_task(periodic_deferred_export_sweep(interval_s=sweep_interval))
yield
sweep_task.cancel()
```

Tests: a lifespan integration test that starts the server, drops a `deferred` row + creates the destination dir, sleeps slightly past the interval, asserts status flipped to `success`.

**Re-triage trigger:** First Sprint 4 PR review or Sprint 5 kickoff — should land before users exercise auto-export at scale.

---

### Sprint 4 no. 2 — Dashboard upload does not send `profile_id` (MEDIUM)

**Symptom:** `POST /api/notebook/transcribe/upload` accepts a `profile_id` form-param (Sprint 4 commit B); without it, `_run_transcription` receives `profile_snapshot=None` and `trigger_auto_actions` short-circuits as a no-op. Result: even when the user toggles auto-summary / auto-export ON in their profile, NOTHING fires. The end-to-end Story 6.2 / 6.3 flow does not work from the dashboard until the upload component selects an active profile and forwards its id.

**Why deferred:** Backend contract is in place + tested; the dashboard upload path's profile-selection UX was scoped out of Sprint 4 to keep the LOC budget under 4000.

**Defense shape:**
1. Add an "active profile" pointer in dashboard state (e.g. `useActiveProfile` hook or first-row default from `apiClient.listProfiles()`).
2. In the upload form (likely `dashboard/components/views/SessionView.tsx` or wherever `POST /transcribe/upload` is called), append `fd.append('profile_id', String(profileId))`.
3. Vitest: add a test that the upload mutation includes `profile_id` in its FormData.

**Re-triage trigger:** First user reports "auto-summary doesn't fire" or Sprint 5 dashboard polish.

---

### Sprint 4 no. 3 — `AutoActionStatusBadge` not rendered in recording detail view (MEDIUM)

**Symptom:** The component, hook, and apiClient method are delivered + UI-contract-ratified (Sprint 4 commit E), but `AudioNoteModal.tsx` (the recording detail surface) does NOT yet read `recording.auto_summary_status` / `recording.auto_export_status` and render the badges. End result: even when auto-actions ran successfully, the user has no visible signal that they happened, no retry button on failure, no held-state surface. Story 6.6 AC1 ("badge appears on recording detail view") is not satisfied end-to-end.

**Why deferred:** Same as no. 2 — frontend integration scoped out to keep Sprint 4 commits in budget; the component was prioritized to land with the UI-contract update.

**Defense shape:** Inside `AudioNoteModal.tsx`, near the existing summary panel:

```tsx
import { AutoActionStatusBadge, statusToBadgeProps } from '../recording/AutoActionStatusBadge';
import { useAutoActionRetry } from '../../src/hooks/useAutoActionRetry';

const retry = useAutoActionRetry(recording.id);
const summaryProps = statusToBadgeProps(recording.auto_summary_status, 'auto_summary',
  { error: recording.auto_summary_error });
const exportProps = statusToBadgeProps(recording.auto_export_status, 'auto_export',
  { error: recording.auto_export_error, path: recording.auto_export_path });

{summaryProps && <AutoActionStatusBadge recordingId={recording.id} recordingName={recording.title}
  actionType="auto_summary" {...summaryProps} onRetry={() => retry.mutate('auto_summary')} />}
{exportProps && <AutoActionStatusBadge ... actionType="auto_export" ... />}
```

Plus: extend the recording-detail Pydantic + TypeScript types to surface the new columns (already in DB, not yet on the response model).

**Re-triage trigger:** Same as no. 2.

---

### Sprint 4 no. 4 — Diarization-review attribution-cycle ←/→ keys are no-op placeholder (MEDIUM)

**Surfaced 2026-05-04 during Sprint 3 (Story 5.9).** `DiarizationReviewView.onListKeyDown` consumes `ArrowLeft` / `ArrowRight` with `preventDefault()` so the canonical Diarization-Review Keyboard Contract (PRD §900–920) doesn't bubble them to surrounding controls — but the key handler body is empty. The Keyboard Contract row "←/→ Switch attribution within a focused turn" is therefore not implemented end-to-end.

**Why deferred:** Sprint 3's primary goal was the canonical Keyboard Contract shape (composite-widget listbox, aria-activedescendant, single tab stop) plus the lifecycle-driving keys (Enter/Esc/Space). Attribution cycling requires a per-turn alternative-speaker list (which speakers are plausible candidates for THIS turn) — that data plumbing is its own design decision and was scoped out to keep Sprint 3 within LOC budget.

**Defense shape:** Two pieces:

1. **Backend** — extend `GET /api/notebook/recordings/{id}/diarization-confidence` (or add a sibling endpoint) to return `alternative_speakers: string[]` per turn. The list is the set of OTHER speaker_ids that appear in the recording, ordered by descending similarity score (or simply by appearance order if pyannote doesn't expose similarity).

2. **Frontend** — `DiarizationReviewView` tracks `activeAttributionIndex` per turn:

```tsx
case 'ArrowRight':
  e.preventDefault();
  setActiveAttributionIndex((prev) => {
    const turn = visibleTurns[activeIndex];
    const alts = turn?.alternative_speakers ?? [];
    return Math.min(prev + 1, alts.length - 1);
  });
  break;
case 'ArrowLeft':
  e.preventDefault();
  setActiveAttributionIndex((prev) => Math.max(prev - 1, 0));
  break;
```

The current attribution is `turn.alternative_speakers[activeAttributionIndex] ?? turn.speaker_id`. On Enter (accept), the chosen attribution is recorded in the decision payload as `speaker_id` so the JSON the server stores reflects the user's choice.

**Re-triage trigger:** First user feedback that "the ←/→ keys do nothing" OR Sprint 5 (next sprint that touches the review view).

