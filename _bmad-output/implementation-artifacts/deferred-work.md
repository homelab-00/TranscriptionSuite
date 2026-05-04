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

