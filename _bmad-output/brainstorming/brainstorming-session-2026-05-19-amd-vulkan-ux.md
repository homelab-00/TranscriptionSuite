---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'AMD/Vulkan end-user UX polish — launching whisper-server.exe and docker from the TranscriptionSuite.exe frontend'
session_goals: 'Identify all the ideas and approaches for making the AMD/Vulkan workflow seamless from the frontend, so an end user never has to touch the command line'
selected_approach: 'user-selected'
techniques_used: ['Six Thinking Hats']
ideas_generated: [12]
workflow_completed: true
session_active: false
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Luke
**Date:** 2026-05-19

## Session Overview

**Topic:** AMD/Vulkan end-user UX polish — launching whisper-server.exe and docker from the TranscriptionSuite.exe frontend
**Goals:** Identify all the ideas and approaches for making the AMD/Vulkan workflow seamless from the frontend, so an end user never has to touch the command line

### Session Setup

Current pain points:
1. User must manually launch `whisper-server.exe` with a hand-crafted CLI command (specifying model path)
2. User must manually `docker compose up` from `%APPDATA%\TranscriptionSuite\docker`
3. User must manually edit `.env` to set `MAIN_TRANSCRIBER_MODEL` and `WHISPERCPP_SERVER_URL`
4. All three steps must be done in the correct order before launching TranscriptionSuite.exe

**Architecture constraint discovered during session:** `whisper-server` cannot run inside a Docker container on Luke's machine — his CPU lacks AVX2 instructions which the containerised build requires. Therefore `whisper-server.exe` must run natively on Windows. Docker only acts as the backend orchestrator; it routes audio to the native exe via `http://host.docker.internal:8080`.

**Current branch mis-diagnosis:** `docker-compose.vulkan-wsl2.yml` defines a `whisper-server` Docker service that will never start on this machine. The correct compose stack for native-exe AMD/Vulkan is `docker-compose.yml` + `docker-compose.desktop-vm.yml` only, with `WHISPERCPP_SERVER_URL=http://host.docker.internal:8080`.

Desired end state: Everything orchestratable from within TranscriptionSuite.exe — model selection drives native `whisper-server.exe` launch, "Start Local" (vulkan-wsl2 profile) triggers the full stack, no terminal ever opened.

---

## Technique Execution — Six Thinking Hats

### White Hat — Facts & Information

**Confirmed facts:**
- `whisper-server.exe` path is user-configurable; will be placed at `%APPDATA%\TranscriptionSuite\whisper-server\whisper-server.exe` by the installer — auto-discoverable, no config UI needed
- Model `.bin` files are user-configurable; will follow the same storage pattern as CUDA models (Docker volume named `models` / known subfolder under APPDATA)
- `WHISPERCPP_SERVER_URL=http://host.docker.internal:8080` must be written to `.env` when vulkan-wsl2 is selected — currently hand-written by Luke, not auto-written by the UI
- `WHISPERCPP_MODEL` (container path like `/models/ggml-small.en.bin`) is already handled by `dockerManager.ts`
- `MAIN_TRANSCRIBER_MODEL` is already written to `.env` by the Instance Settings UI
- `docker-compose.vulkan-wsl2.yml` includes a `whisper-server` Docker service — this is wrong for the native-exe approach and should be bypassed
- Electron can spawn child processes; `process.env.APPDATA` gives the APPDATA path
- The `startServerWithOnboarding` → `docker.startContainer` → `dockerManager.startContainer` IPC chain is the existing "Start Local" path — all changes can be gated here
- `whisper-server.exe` is a separate process; it outlives the app today (no lifecycle ownership)
- `runtimeProfile === 'vulkan-wsl2'` branch already exists in `ServerView.tsx` and `dockerManager.ts` — the conditionals are in place

### Red Hat — Emotions & Gut Feelings

- Current setup feels like a developer environment, not a consumer app — three terminal steps before launching is a support-ticket factory
- End users without technical background will be frustrated and give up
- One button = pleasant, "it just works" experience
- Emotional risk: **silent failures** — if whisper-server.exe starts with the wrong model or can't find the file, and no error surfaces, the user just sees "transcription not working" with no clue why
- Fear: double-launching whisper-server.exe (mitigated by PID file — if the UI owns the process, it can prevent this by design)

### Yellow Hat — Benefits

- A non-technical user downloads TranscriptionSuite, selects AMD/Vulkan, clicks Start Local — it works
- No docs, no terminal, no `.env` editing, ever
- Whisper-server.exe lifecycle owned by the app = clean shutdowns, no orphaned processes
- This pattern (UI owns process lifecycle) becomes the blueprint for NVIDIA/CUDA later
- NVIDIA/CUDA path remains completely untouched in this pass

### Black Hat — Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `whisper-server.exe` not at expected APPDATA path | Clear error: "Transcription server not found. Please reinstall." |
| Model `.bin` missing | Pre-flight check before launch → trigger existing model download flow if absent |
| Port 8080 occupied by unknown process | Hard fail with message: "Port 8080 is in use. Please free it before starting." |
| App crashes, `whisper-server.exe` stays alive; next launch tries to start it → port already bound | PID file: on startup read PID, kill if alive, then start fresh |
| Model path mismatch (user picks model A, `.bin` for A is missing) | Pre-flight check per model selection, not just at startup |

### Green Hat — Creative Solutions

- **Model selector IS the launcher:** selecting a model triggers the pre-flight + restart sequence in the background — no separate "start server" button
- **Model switching as first-class action:** user can change model or switch to CPU-only at any time from the UI; under the hood: stop whisper-server.exe → update `.env` → restart with new model
- **Extended health badge:** existing badge already turns green when docker is up; extend it to require whisper-server.exe also healthy before going green

### Blue Hat — Orchestration

Correct "Start Local" sequence for vulkan-wsl2 profile:

1. **Port 8080 check** — if occupied by unknown process → fail with message
2. **Kill existing whisper-server.exe** — read PID file, kill if alive
3. **Model pre-flight** — does selected `.bin` exist? → trigger download if not
4. **Write `.env`** — `WHISPERCPP_SERVER_URL=http://host.docker.internal:8080`, `WHISPERCPP_MODEL`, `MAIN_TRANSCRIBER_MODEL`
5. **Launch `whisper-server.exe`** — with `--model <path> --host 0.0.0.0 --port 8080` → write PID file
6. **Start docker compose** — `docker-compose.yml` + `docker-compose.desktop-vm.yml` only (no vulkan-wsl2 overlay for native-exe approach)
7. **Poll health badge** — green when both docker backend AND whisper-server.exe respond healthy

All steps gated behind `runtimeProfile === 'vulkan-wsl2'` — zero impact on NVIDIA/CPU paths.

---

## Idea Organization and Prioritization

### Theme 1: Process Lifecycle Management
- **PID File Lifecycle** — write PID on launch, kill on startup (crash recovery), kill on clean exit
- **Port 8080 Hard Fail** — pre-flight check; clear error if port taken by unknown process
- **Extended Health Badge** — green requires docker + whisper-server.exe both healthy
- **Model Switching** — stop/restart native exe when user changes model selection

### Theme 2: Zero-Touch Setup
- **Auto-Discovery** — installer places exe at known APPDATA path; app finds it without any config UI
- **"Start Local" as Unified Trigger** — one button, existing entry point, extended not replaced
- **WHISPERCPP_SERVER_URL Auto-Write** — `http://host.docker.internal:8080` written automatically for vulkan-wsl2 (closes last manual `.env` edit)
- **Model Pre-flight + Download** — check `.bin` before launch; reuse existing model download infrastructure

### Theme 3: User Experience
- **One-Button North Star** — download → pick AMD/Vulkan → click Start → works
- **Human-Readable Errors** — every failure mode surfaces a clear, actionable message; nothing silent
- **AMD/Vulkan as Blueprint** — same pattern extends to NVIDIA/CUDA process ownership later

### Breakthrough Concept: Correct Compose Stack
The `docker-compose.vulkan-wsl2.yml` Docker service must be bypassed for native-exe AMD/Vulkan. The correct stack is `docker-compose.yml` + `docker-compose.desktop-vm.yml` only. This is a critical fix — without it "Start Local" with vulkan-wsl2 will always fail on AVX2-lacking hardware.

---

## Action Plan — Implementation Order

### Step 1 — Fix the compose stack (prerequisite, unblocks everything)
- In `dockerManager.ts::composeFileArgs`: for `vulkan-wsl2` profile on Windows, do NOT add `docker-compose.vulkan-wsl2.yml`
- Set `WHISPERCPP_SERVER_URL=http://host.docker.internal:8080` (not `http://whisper-server:8080`) for vulkan-wsl2 on Windows
- **Impact:** "Start Local" stops trying to start the AVX2 container. Minimal change, maximum unblock.

### Step 2 — Native process launcher in `dockerManager.ts`
- New function: `launchWhisperServer(modelPath: string): Promise<number>` (returns PID)
- Reads exe path from `%APPDATA%\TranscriptionSuite\whisper-server\whisper-server.exe`
- Spawns: `whisper-server.exe --model <modelPath> --host 0.0.0.0 --port 8080`
- Writes PID to `%APPDATA%\TranscriptionSuite\whisper-server.pid`
- Called from `startContainer` when `runtimeProfile === 'vulkan-wsl2'`

### Step 3 — PID file lifecycle management
- New function: `killExistingWhisperServer(): Promise<void>`
- Reads PID file; if process alive, kills it; deletes PID file
- Called at start of `startContainer` (crash recovery) and from `stopContainer` (clean exit)

### Step 4 — Pre-flight checks
- Port 8080 probe: if occupied by a PID not matching our PID file → throw with user-facing message
- Model `.bin` existence check: if file missing → surface download prompt (reuse existing model manager flow)
- Both gated behind `runtimeProfile === 'vulkan-wsl2'`

### Step 5 — Health badge extension (minimal frontend touch)
- Extend the health check that drives the badge to also query `localhost:8080/health` when vulkan-wsl2 is active
- No new UI components — the badge already exists

---

## Session Summary

**Problem:** AMD/Vulkan transcription works but requires three manual terminal steps and `.env` editing before the app can be used. Non-technical users cannot set it up.

**Root cause of current branch failure:** `docker-compose.vulkan-wsl2.yml` runs whisper-server inside Docker, which requires AVX2. Luke's CPU lacks AVX2. Solution: run whisper-server.exe natively on Windows; Docker only handles the backend.

**Solution architecture:** TranscriptionSuite.exe owns the full lifecycle — it launches `whisper-server.exe` natively before starting docker compose, manages it via PID file, and cleans it up on exit. The UI entry point ("Start Local" with vulkan-wsl2 selected) remains unchanged; all new logic is additive and gated on `runtimeProfile === 'vulkan-wsl2'`.

**Constraint preserved:** NVIDIA/CUDA and CPU paths are completely unaffected. All new code is inside `if (runtimeProfile === 'vulkan-wsl2')` branches in `dockerManager.ts` and the health check.

**Smallest change with biggest impact:** Step 1 — fixing the compose stack selection and the `WHISPERCPP_SERVER_URL` value. This alone makes "Start Local" stop failing. Steps 2–5 add the automation on top.
