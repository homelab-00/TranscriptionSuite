---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Watch folder feature for auto-processing transcription files (GH Issue #41)'
session_goals: 'Explore architecture options, cross-platform strategy, edge cases, UI integration, and lifecycle management'
selected_approach: 'ai-recommended'
techniques_used: ['Morphological Analysis', 'Reverse Brainstorming', 'Six Thinking Hats']
ideas_generated: ['Arch #1 Queue Unification', 'Arch #2 Electron-as-Gateway', 'Arch #3 Config Persistence Split', 'Arch #4 Client-Side Unified Queue', 'Arch #5 Watcher-as-Queue-Feeder', 'Arch #6 Multi-User Future-Proofing', 'Arch #7 Infinite File Picker', 'Arch #8 Lightweight File Fingerprint Ledger', 'Idea #19 Activity Log', 'Idea #20 Drag-to-Watch', 'Idea #21 Queue Estimates', 'Idea #22 First-Run Hint', 'R1-R16 Requirements', 'Decision #1 Pause-Cancel Race']
session_active: false
workflow_completed: true
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-03-22
**GitHub Issue:** #41 — "Add the ability to watch a folder, auto processing whatever files are placed in it"
**Techniques Used:** Morphological Analysis, Reverse Brainstorming, Six Thinking Hats

## Session Overview

**Topic:** Watch folder feature — auto-detect files placed in a watched folder and queue them for transcription (GH Issue #41)
**Goals:** Explore architectural options (server-side vs Electron-side watching), identify the simplest cross-platform approach given Docker constraints, surface edge cases early, and define UI/lifecycle behavior
**Target Platforms:** Linux KDE Wayland (primary), Windows 11, macOS

### Context Guidance

_Focus areas: watcher strategy (server vs Electron vs both), cross-platform library choice (watchdog vs chokidar), edge cases (partial writes, duplicates, debouncing, restart behavior), UI placement in Session Import & Notebook Import tabs, lifecycle (toggle, config persistence, visual indicators). Server runs in Docker._

---

## Architecture Decisions

### Core Pattern: Electron-as-Gateway / "Infinite File Picker"

The watcher runs in the **Electron main process** using **chokidar** (Node). It watches for new audio files, validates readiness, and submits them to the server via the **existing API** — the same code path as manual file import. The server never knows or cares that a file came from a watcher. Zero server-side changes for the core feature.

### Locked Design Parameters

| Parameter | Decision | Rationale |
|-----------|----------|-----------|
| Watcher Location | Electron main process | Direct filesystem access; avoids Docker volume mounting complexity |
| Library | chokidar (Node) | Battle-tested (~40M weekly downloads), abstracts inotify/FSEvents/ReadDirectoryChanges, cross-platform |
| File Readiness | Three-point size-stability (0s → 2s → 4s) | Handles slow copies, USB drives, browser downloads |
| UI Placement | New "Folder Watch" section in both import sub-tabs | Session Import: watch folder + toggle, output to existing output folder. Notebook Import: independent watch folder + toggle, follows existing notebook logic |
| Lifecycle | Active while toggle on + server running | Path persisted in config; toggle defaults to OFF on restart (safety) |
| Queuing | Unified client-side queue, immediate add, job-type badges | 4 types: session-normal, session-auto, notebook-normal, notebook-auto |

### Key Architectural Concepts

**[Arch #1] Queue Unification:** Single shared queue across both import tabs. Single source of truth. 4 job types distinguished by small UI badge/icon. This is an improvement even without the watch folder — two separate queues was a latent UX problem.

**[Arch #2] Electron-as-Gateway:** Watcher lives in Electron main process. Detects files, validates type and readiness, submits via existing server API. Server stays unchanged.

**[Arch #3] Config Persistence Split:** Watch folder path persisted in Electron config (survives restart). Toggle state is ephemeral (defaults OFF on restart). Prevents surprise auto-processing if user restarts after forgetting a watcher was active.

**[Arch #4] Client-Side Unified Queue:** Queue state lives in frontend (React context/store, above tab level). Server remains single-slot, processes one job at a time. All queue intelligence is a frontend concern.

**[Arch #5] Watcher-as-Queue-Feeder:** Watcher pushes file paths into the unified queue via IPC. The queue is origin-agnostic — only the job-type metadata tag differs between manual and auto-watch jobs.

**[Arch #6] Multi-User Future-Proofing:** Add `origin` field to job metadata (`manual | watch-session | watch-notebook`). Forward-compatible with future server-side queue rework.

**[Arch #7] "Infinite File Picker":** Conceptually, the watcher is just an automated version of repeatedly clicking "Add Files." Same API endpoint, same processing path, same result handling. No special server APIs, no special processing code.

**[Arch #8] Lightweight File Fingerprint Ledger:** For each processed file, store `filename + fileSize + xxhash of first 64KB`. On watcher startup, check new files against ledger to prevent reprocessing. Use `xxhash-wasm` (pure WASM, zero native deps — safe for Electron cross-platform). Hashing first 64KB means even multi-GB files fingerprint in microseconds. Write ledger atomically (temp file → rename) to prevent corruption. Clear ledger when watch folder path changes.

### Key Constraint

**Single-Slot Server:** Server processes one job at a time (`try_start_job()` returns 409 if busy). The client-side queue serializes submissions. Watch folder makes this limitation more visible to users when large batches are queued. Server-side queue rework is planned for the future but out of scope for this feature.

---

## Requirements (from Reverse Brainstorming)

16 failure scenarios were explored and flipped into concrete requirements.

### File Handling

| ID | Requirement | Source |
|----|------------|--------|
| R1 | Three-point size-stability check (0s → 2s → 4s) for file readiness | Fail #1: Half-written file |
| R2 | Audio file extension whitelist — only queue supported formats (verify server's list during implementation) | Fail #2: Non-audio files |
| R3 | Batch watcher events in ~3s window, add all at once as single queue update. Summary notification ("27 files auto-queued from Session Watch") | Fail #4: 200-file avalanche |
| R10 | Output folder resolved at processing time, not queue time — avoids stale path if user changes output mid-queue | Fail #9: Output folder change |
| R11 | No deduplication — user responsible for adding correct files. Same file dropped twice = processed twice | Fail #10: Duplicate file |

### Queue & Lifecycle

| ID | Requirement | Source |
|----|------------|--------|
| R4 | Bulletproof watcher cleanup on app close — register in `app.on('before-quit')` and `window.on('close')`, track and destroy all chokidar instances | Fail #5: Zombie watcher |
| R5 | Pause file discovery when server unreachable, resume on reconnect | Fail #6: Server crash |
| R6 | Block same folder for both watchers — show explanation message if user tries | Fail #7: Double-watch |
| R7 | Queue state must live above tab level (context/store) — tab navigation must never destroy queue state (verify existing behavior) | Fail #8: Tab navigation |
| R8 | Queue **pause/resume button**. On pause: cancel current job via `cancel_job()`, discard partial result, file returns to front of queue as "pending". Server becomes free for normal transcription/live mode. On resume: restart cancelled file from scratch, continue queue | Fail #17: Import vs. normal usage conflict |
| R9 | Persistent "queue paused" indicator visible across all tabs when paused (e.g., "Queue paused — 43 files waiting") | Fail #18: Forgotten pause |

### Platform & Robustness

| ID | Requirement | Source |
|----|------------|--------|
| R12 | Monitor watched folder accessibility. Show amber/red indicator if folder disappears (e.g., USB unplugged). Auto-recover when path becomes accessible again | Fail #11: Folder disappears |
| R13 | Use `\\?\` prefix for Windows paths in file operations. Document that deeply nested paths may cause issues | Fail #13: Windows 260-char limit |
| R14 | Warn user that network drives may have delayed file detection (chokidar handles polling fallback automatically) | Fail #14: Network drive latency |
| R15 | Processed-file ledger — filename + fileSize + xxhash-first-64KB. Checked on watcher startup. Cleared when watch folder path changes. Atomic writes to prevent corruption | Fail #15: Reprocessing on restart |
| R16 | Leave processed files in place in the watch folder. Rely on ledger to prevent reprocessing | Fail #16: What happens to original file |

### Design Decision

**[Decision #1] Pause-Cancel Race Condition:** If user hits pause but the current job finishes before the server's `cancel_job()` takes effect — keep the result. Don't throw away a completed transcription. The file moves to "done" in the queue and the next file simply doesn't start (because queue is now paused).

---

## UI Specification

### Session Import Tab — New "Folder Watch" Section

- **Watch Folder** field: folder picker (same style as existing output folder picker)
- **Watch toggle**: start/stop switch
- Auto-transcriptions use the existing output folder setting for that tab
- Auto-queued jobs tagged as `session-auto` in unified queue

### Notebook Import Tab — New "Folder Watch" Section

- **Watch Folder** field: folder picker (configured independently from Session Import watch folder)
- **Watch toggle**: start/stop switch
- Auto-transcriptions follow existing notebook import logic (auto-added to notebook by creation date)
- Auto-queued jobs tagged as `notebook-auto` in unified queue

### Unified Queue (shared across both import tabs)

- Single queue displaying all 4 job types: `session-normal`, `session-auto`, `notebook-normal`, `notebook-auto`
- Each job type has a small distinguishing badge/icon (e.g., eye icon for auto-watch jobs, manual icon for normal imports)
- **Pause/Resume button** for the entire queue
- Queue position visible for all pending jobs
- Persistent "paused" indicator visible across all tabs when queue is paused

---

## Prioritization

### Must-Have (v1)

- Electron watcher with chokidar (Arch #2, #5, #7)
- Unified queue with 4 job types and badges (Arch #1, #4)
- Queue pause/resume with cancel (R8, R9, Decision #1)
- Three-point file readiness check (R1)
- Audio extension whitelist (R2)
- Event batching with summary notification (R3)
- Processed-file ledger with xxhash (Arch #8, R15, R16)
- Watch folder UI in both import tabs with independent config
- Toggle defaults OFF on restart (Arch #3)
- Duplicate folder blocking with explanation (R6)
- Watcher cleanup on quit (R4)

### Should-Have (v1 if time allows)

- Server disconnect handling — pause discovery when unreachable (R5)
- Folder accessibility monitoring with amber/red indicator (R12)
- Late-resolve output folder at processing time (R10)
- Queue state above tab level — verify existing behavior (R7)

### Nice-to-Have (post-v1)

- Watch folder activity log — expandable panel showing watcher events (Idea #19)
- Drag-to-watch shortcut — drag folder onto watch field to set it (Idea #20)
- Queue time estimates — "3 files ahead — ~12 min remaining" (Idea #21)
- First-run hint suggesting watch folder setup for new users (Idea #22)
- Windows long path prefix (R13)
- Network drive warning (R14)
- Multi-user origin metadata on job submissions (Arch #6)

---

## Suggested Implementation Phases

### Phase 1: Queue Unification + Pause

Refactor the existing per-tab queues into a single shared queue store (React context or Zustand). Add job-type metadata. Add pause/resume button with cancel. Add persistent pause indicator. This is independently useful and de-risks the watch folder work.

### Phase 2: Session Import Watcher

Add chokidar watcher in Electron main process. Wire up IPC (main → renderer). Add "Folder Watch" section to Session Import tab (folder picker + toggle). Implement file readiness checks, extension filter, event batching, processed-file ledger. Config persistence for watch folder path. End-to-end for one import type.

### Phase 3: Notebook Import Watcher

Extend to Notebook Import tab with independent watch folder config. Add duplicate folder blocking (prevent same folder on both watchers). Verify all edge cases work for both import paths.

### Phase 4: Polish

Folder accessibility indicators (R12), server disconnect handling (R5), activity log, drag-to-watch, queue estimates, first-run hint, any remaining nice-to-haves.

---

## Existing Architecture Notes (discovered during session)

### Current Job Tracker

- **File:** `server/backend/core/model_manager.py` — `TranscriptionJobTracker` class
- Single-slot model: one job at a time, `try_start_job()` returns 409 if busy
- Per-user tracking via `active_user` field
- Supports `cancel_job()` / `is_cancelled()` — needed for queue pause feature
- Progress tracking via `update_progress(current, total, message)`
- Status polling via `GET /api/admin/status`

### Current Frontend Queue

- **File:** `dashboard/src/hooks/useImportQueue.ts` — client-side `ImportJob[]` array
- Processes files one-at-a-time sequentially
- Polls `/api/admin/status` every 5 seconds for completion
- Wraps in `useSessionImportQueue.ts` for Session Import tab
- **This is what gets unified in Phase 1**

### Key Server Endpoints

- `POST /api/transcribe/audio` — synchronous transcription (blocks until done)
- `POST /api/notebook/transcribe/upload` — async, returns 202 + job_id
- `GET /api/admin/status` — returns job tracker status for polling

---

## Session Summary

### Creative Facilitation Narrative

This session used a three-phase approach — map the space (Morphological Analysis), break it (Reverse Brainstorming), evaluate it (Six Thinking Hats). The Docker architecture constraint immediately collapsed the watcher-location decision, which anchored all subsequent exploration. Bill's unified queue insight (raised during morphological analysis) was the session's most impactful contribution — it elevated the feature from "add a watcher" to "improve the whole queue architecture." The reverse brainstorming phase uncovered the critical pause/resume requirement — a UX need that only becomes obvious when you imagine daily usage patterns.

### Key Achievements

- Complete architecture decided: Electron watcher → chokidar → IPC → unified client-side queue → existing server API
- 16 failure scenarios explored, each converted to a concrete requirement
- Queue unification identified as an architectural improvement that benefits the whole app
- Pause/resume identified as essential for coexistence with normal app usage
- Processed-file ledger design prevents the most likely user complaint (reprocessing on restart)
- 4-phase implementation plan provides incremental delivery with each phase independently useful

### Next Steps

1. Use this document as input for a formal architecture/planning session
2. Phase 1 (Queue Unification + Pause) can begin independently — it improves the app even without the watch folder
3. Verify existing audio format whitelist and queue state behavior during Phase 1 implementation
