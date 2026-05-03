---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Phantom models download notification on container restart'
session_goals: 'Root cause analysis + handoff-ready tech spec for fix'
selected_approach: 'Progressive Technique Flow'
techniques_used: ['Five Whys + Question Storming', 'Constraint Mapping + Assumption Reversal', 'First Principles Thinking + SCAMPER', 'Decision Tree Mapping + Solution Matrix']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-04-01

## Session Overview

**Topic:** Why does the dashboard show a brief "models" download notification on every existing container start when models are already fully downloaded and working?

**Goals:**
1. Find the root cause
2. Produce a handoff-ready tech spec for the fix

### Session Setup

- **Approach:** Progressive Technique Flow — start broad, then systematically narrow focus
- **Context:** User has set up the app, downloaded runtime + model, ran transcriptions successfully across app restarts. Despite this, every container start briefly flashes the "models" download floating notification in the bottom-right corner before it disappears.

## Phase 1: Five Whys — Root Cause Chain

1. **Why does the notification appear?** → `DownloadNotifications.tsx` renders a card when `downloadStore` has a non-dismissed item with `type: 'ml-model'`
2. **Why does the store get an item?** → `useBootstrapDownloads` calls `store.addDownload()` on receiving a `start` IPC event
3. **Why does IPC fire?** → Bootstrap log parser matches `"Preloading transcription model"` in container logs → emits `{ action: 'start', type: 'ml-model', id: 'model-preload' }`
4. **Why does the server log this every restart?** → `main.py:493` always calls `load_transcription_model()` when GPU is healthy and model is configured — correct behavior (loads cached weights into VRAM)
5. **Why does the parser treat this as a download?** → **No distinction between "load from cache" and "download from internet"** — both match the same pattern and emit the same `ml-model` event type

**Root Cause:** The bootstrap log parser conflates model loading (cached weights → GPU VRAM, ~3-5s) with model downloading (HuggingFace → disk, minutes). Same log pattern, same event type, same notification treatment.

## Phase 2: Evidence & Eliminated Hypotheses

- **Confirmed:** The server log `"Preloading transcription model..."` fires on every startup (`main.py:493`)
- **Confirmed:** Parser pattern at `dockerManager.ts:1969-1973` maps this to `type: 'ml-model'`
- **Confirmed:** Notification shows indeterminate pulsing progress (no real progress tracking for preload)
- **Eliminated:** wav2vec2 alignment model — has no parser pattern at all, produces no notification
- **Eliminated:** Actual download happening silently — downloads go through `downloadModelToCache`, a completely different code path

## Phase 3: Fix Design — Hybrid Approach (A+B)

**Server side:** Emit distinct log line `"Loading transcription model from cache..."` (replaces `"Preloading transcription model..."`)
**Client side:** New `model-preload` event type with subtle UI treatment:
- Slate-colored icon (not orange)
- No progress bar
- Label: "Loading Model" (not "Transcription Model" with download semantics)
- Same auto-dismiss on completion

## Phase 4: Tech Spec

**Output:** `_bmad-output/implementation-artifacts/spec-fix-phantom-model-preload-notification.md`

7 files changed across server + client:
1. `server/backend/api/main.py` — new log line
2. `dashboard/electron/dockerManager.ts` — new event type + updated patterns
3. `dashboard/src/types/electron.d.ts` — type union update
4. `dashboard/src/stores/downloadStore.ts` — type union update
5. `dashboard/components/ui/DownloadNotifications.tsx` — preload-specific rendering
6. `dashboard/components/views/DownloadsPanel.tsx` — preload-specific labels
7. `dashboard/electron/preload.ts` — type union update
