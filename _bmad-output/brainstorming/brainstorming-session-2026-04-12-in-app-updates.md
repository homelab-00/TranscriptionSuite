---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'In-app self-update capability for the TranscriptionSuite Electron dashboard'
session_goals: 'Enable users to complete the full Dashboard update flow (download + install) from within the app. GitHub remains host/distributor.'
selected_approach: 'progressive-flow'
techniques_used: ['cross-pollination', 'morphological-analysis', 'scamper', 'decision-tree-mapping']
ideas_generated: 60
context_file: ''
workflow_completed: true
locked_decisions:
  - LIB-1: electron-updater is the foundation
  - INST-3: block install during active transcription (hard constraint — data-loss invariant)
  - PROJ-1: server compatibility guard required
  - Profile P2 + axis-5=C: VSCode-like UX with idle-queue install
  - D1: manifest.json asset per release (version, compatibleServerRange, SHA-256, releaseType)
  - D2: main process queries /api/admin/status directly (no IPC bridging)
  - D3: Dashboard already controls Docker via dockerManager.ts — reuse for "update server first"
  - D4: unsigned v1 — Linux auto-update works; Mac/Win manual-download until signing set up
  - D5: checksums rolled into manifest.json
  - D6: cache last 1 previous installer for rollback
---

# Brainstorming Session: In-App Dashboard Updates

**Facilitator:** Bill
**Date:** 2026-04-12
**Outcome:** Implementation-ready spec

---

## Session Overview

**Topic:** In-app self-update capability for the TranscriptionSuite Electron dashboard.

**Goal:** Eliminate the manual GitHub-visit step. User clicks a button in the app → new version installed. GitHub remains the host/distributor.

**Scope:** Dashboard (Electron) only. The Docker server has its own update path (`docker pull`), separately handled.

**Journey:** Progressive Technique Flow — Cross-Pollination → Morphological Analysis → SCAMPER → Decision Tree Mapping.

---

## Current State (Pre-Feature)

- `dashboard/electron/updateManager.ts` already polls GitHub Releases API every 24h (configurable)
- Setting `app.updateChecksEnabled` in Settings > App > Update Checks
- When a new version is found, an OS-native `Notification` fires (`updateManager.ts:318-352`)
- **No download or install path exists** — the notification is purely informational
- Dashboard packaging: `electron-builder` 26.8.1 → Linux AppImage, Windows NSIS, macOS DMG+ZIP
- Target platforms: Linux KDE Wayland (primary), Windows 11, macOS

---

## Concept (One Sentence)

When "Check for updates" is on, the Dashboard fetches a `manifest.json` from each GitHub release, verifies server compatibility *before* downloading, streams the release asset via `electron-updater`, shows a single stateful banner in the main window plus a progress row in Settings, presents release notes + server-update offer in one pre-install modal, verifies SHA-256, blocks "Quit & Install" during active transcription and prompts the user once idle, and caches the previous installer for watchdog rollback on repeated launch failures.

---

## Locked Decisions

### Core technology
| | Decision | Notes |
|---|---|---|
| **LIB-1** | Use `electron-updater` (sibling of electron-builder) | Canonical answer; GitHub provider built in |
| **INST-3** | Block install during active transcription | Hard constraint — respects "AVOID DATA LOSS AT ALL COSTS" invariant |
| **PROJ-1** | Server compatibility guard required | Dashboard + Dockerized server must stay on compatible versions |

### Profile: P2 (VSCode-like) + axis 5 = C (idle-queue)
| Axis | Choice |
|---|---|
| Download trigger | Auto-approved via Settings toggle |
| Install trigger | Explicit "Quit & Install" button (text adopted from Electron conventions) |
| UX surface | Stateful banner in main window + Settings row |
| Release channel | Stable only (v1) |
| Active-job policy | Download never blocked; install auto-queued until transcription idle |
| Server mismatch | One-click "update server first" via existing `dockerManager` |

### Settled by design
| Area | Choice | Rationale |
|---|---|---|
| Verification | SHA-256 from `manifest.json` + electron-updater defaults | Closes Linux's lack-of-codesign gap |
| Release notes | Render GitHub release `body` as markdown in pre-install modal | Payload already fetched; was being discarded |
| Rollback | Cache previous installer in `userData/`; watchdog restores on 3 failed launches | Last-1-version kept (~150MB) |
| Errors | Toast + local logs | No telemetry unless user opts in (consistent with project posture) |

### Detailed decisions (D1–D6)
- **D1 `manifest.json`** per release, shape below, ~200 bytes, CI-generated:
  ```json
  {
    "version": "1.3.3",
    "compatibleServerRange": ">=1.4.0 <2.0.0",
    "sha256": {
      "TranscriptionSuite.AppImage": "abc…",
      "TranscriptionSuite-Setup.exe": "def…",
      "TranscriptionSuite.dmg": "789…"
    },
    "releaseType": "stable"
  }
  ```
- **D2** Main process queries `GET /api/admin/status` directly (same endpoint the renderer polls via `useImportQueue`). No new IPC bridge. 5s timeout, fail-closed (treat unreachable server as "not idle"). **Also fixes an existing data-loss bug in `gracefulShutdown()`** where the Docker container is force-stopped without checking `is_busy`.
- **D3** Dashboard controls Docker via `dashboard/electron/dockerManager.ts` — confirmed. The "update server first" flow reuses `dockerManager.pullServerImage()` (new wrapper) + existing restart infra. **Local Docker only**; remote-server mode shows "update manually, then retry" message.
- **D4** Unsigned for v1. Linux AppImage auto-update works fully. Windows shows SmartScreen on each install. **macOS auto-update effectively broken** without notarization — ship a banner disclaimer: "macOS: please download updates manually from GitHub until code signing is set up."
- **D5** Checksums live in `manifest.json`, not a separate file.
- **D6** Cache last 1 previous installer (~150MB). Deeper history adds cost without proportional value.

---

## Implementation Plan (Milestone Order)

### Dependency DAG
```
M1 (electron-updater wiring) ──┬──► M2 (Banner UI) ──┐
                               │                     │
                               ├──► M3 (Safety gate) ┼──► M5 (Pre-install modal) ──► M6 (Safety/errors) ──► M7 (Platforms)
                               │                     │
                               └──► M4 (Compat guard)┘
```
Critical path: **M1 → M3 → M5 → M6 → M7.** M2 and M4 parallelize after M1.

### M1 — electron-updater wiring (1–2 days)
- Add `electron-updater` dep
- Set `publish.provider = 'github'` with `owner: 'homelab-00', repo: 'TranscriptionSuite'` in electron-builder config
- New `UpdateInstaller` class in `dashboard/electron/` (main process), separate from `updateManager.ts` (which continues to handle checks/polling/manifest-fetch)
- Extend existing IPC: `updates:download`, `updates:install`, `updates:cancelDownload`
- Wire electron-updater events (`update-available`, `download-progress`, `update-downloaded`, `error`) into the existing `UpdateStatus` type
- **Gate**: manual test on local Linux AppImage — download + install completes, app relaunches into new version

### M2 — Banner UI (1 day)
- `<UpdateBanner>` component in dashboard, mounted above `SessionView`
- One component, four visual states driven by status:
  1. `available`: "v1.3.3 available — [Download] [Later]"
  2. `downloading`: "Downloading v1.3.3 — 43%" (inline progress)
  3. `ready`: "v1.3.3 ready — [Quit & Install] [Later]"
  4. `ready_blocked`: "v1.3.3 ready — will install when jobs finish" (disabled install button with tooltip)
- "Later" snoozes banner for 4h (constant; no preference)
- **Gate**: all four states render; dismissal persists across app launches

### M3 — Transcription-safety gate [HARD CONSTRAINT] (1–2 days)
- Extract `isAppIdle()` as shared primitive (new `dashboard/electron/appState.ts` or similar)
  - Queries `GET /api/admin/status` from main process
  - Returns `{ idle: boolean, reason?: string }` — `reason` carries "active transcription" / "server unreachable" / "import in progress" for UI display
  - 5s timeout, fail-closed
- Block `autoUpdater.quitAndInstall()` when `!isAppIdle()`
- On transcription-complete event, check for queued install → show toast: `"Update ready to install — [Install now] [Later]"`
- **Also wire the same predicate into `gracefulShutdown()`** to fix the pre-existing data-loss risk
- **Gate**: start transcription, attempt install → blocked with clear reason; finish transcription → toast appears

### M4 — Server-compatibility guard [HARD CONSTRAINT] (1 day)
- Fetch `manifest.json` asset before downloading the binary (new first step in the update flow)
- Parse `compatibleServerRange` (semver range) + `sha256`
- Compare against current server version (`updateManager` already fetches this via GHCR tag check)
- Branch:
  - **Compatible** → proceed to download
  - **Incompatible + local Docker** → mark pre-install modal to show "update server first" button
  - **Incompatible + remote server** → mark pre-install modal to show "update your remote server manually" instructions (with copy-to-clipboard for `docker compose pull` command)
- **Gate**: manually publish a test release with incompatible range → Dashboard refuses to auto-install

### M5 — Pre-install modal (0.5 day)
- Markdown renderer for GitHub release `body` (reuse any existing markdown component; otherwise add `react-markdown`)
- Show version transition (current → target), compat status, optional server-update CTA
- Buttons:
  - `[Install Dashboard]` — proceeds
  - `[Update Server First]` — visible only on incompatible + local Docker
  - `[Cancel]` — dismisses
- **Gate**: modal shows release notes; server-update button visible only in right conditions

### M6 — Safety & error handling (1–2 days)
- SHA-256 verification of downloaded binary against `manifest.json` hash; abort install on mismatch
- Cache previous installer in `app.getPath('userData')/previous-installer/` before overwriting
- Watchdog: on app start, increment a "launch attempts for current version" counter in store; reset on successful ready-state. If counter hits 3 → offer "Restore previous version" dialog
- Three distinct failure-mode UX paths:
  - **Network failure** — silent retry every 1h, no user notification
  - **Download failure** (partial/corrupt) — toast "Download failed — [Retry]", cache partial for resume
  - **Install failure** — modal with specifics + "Restore previous version" option
- **Gate**: simulate each failure → correct message shown; rollback restores previous binary

### M7 — Platform hardening (2–4 days)
- **Linux AppImage**:
  - Detect `process.env.APPIMAGE`
  - Verify file is writable before starting update
  - If not writable (e.g., mounted read-only): fall back to "download to ~/Downloads, open folder when complete"
  - Test: in-place replacement, respawn, KDE desktop integration prompt if AppImage isn't in `~/Applications`
- **Windows NSIS**: electron-updater handles natively. Test with unsigned installer; document SmartScreen warning in the update flow's UI.
- **macOS DMG**: document as "manual update required until signing is set up". Disable auto-update on macOS in v1; show info banner pointing to GitHub releases page.

---

## Effort Summary

**Total: ~7-12 days solo pace** (could compress to ~5 days if macOS path is deferred entirely).

| Milestone | Effort |
|---|---|
| M1 | 1–2 days |
| M2 | 1 day |
| M3 | 1–2 days |
| M4 | 1 day |
| M5 | 0.5 day |
| M6 | 1–2 days |
| M7 | 2–4 days (AppImage quirks dominate; Mac/Win partially deferred) |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AppImage in read-only location | Medium (network mount, `/opt`) | Update fails | Detect writability, fall back to Downloads-folder flow |
| Active-job detector false negative | Low | Data loss | Always require user tap on toast after idle; never silent install |
| macOS Gatekeeper blocks unsigned update | High | Mac users stuck | v1 ships Mac as manual-download with disclaimer |
| `docker compose pull` timeout on slow connection | Medium | User confused | 10-min timeout + visible progress + explicit abort button |
| Partial download corruption | Low | Install fails | SHA-256 verification from `manifest.json` |
| GitHub API rate limit | Very low | Polling stalls | Add ETag caching to existing polls (not required for v1, deferrable) |
| User manually edits AppImage | Low | Version state confusion | On startup, hash current binary; if mismatch, reset cached `currentVersion` |
| New version crashes on launch | Low | Broken app | Watchdog rollback on 3 failed launches → restore cached previous |

---

## Deferred to Later (Not v1)

- **ETag caching** on GitHub polls ([SCAMP-S2]) — bandwidth optimization, not functional; easy add later
- **Download throttling** during active transcription ([SCAMP-M1]) — polish item
- **Shared download-progress component** with STT model downloads ([SCAMP-P1]) — refactor; separate task
- **Named release channels** (beta/dev) ([PROJ-3]) — architecturally cheap to add; defer to v2 to avoid bikeshed
- **Code signing** — Apple Developer + Windows EV cert — revisit when Mac users complain
- **Update telemetry** — opt-in health signals; v2+
- **macOS auto-update** — unlocked by signing infrastructure

---

## Known Pre-Existing Bug (Related, Worth Tracking Separately)

`dashboard/electron/main.ts:1647-1701` — `gracefulShutdown()` force-stops the Docker container on quit with a 30s timeout but **does not check `/api/admin/status.is_busy` first**. This violates the "AVOID DATA LOSS AT ALL COSTS" invariant from `CLAUDE.md`. An in-progress transcription can be killed mid-job.

**M3's `isAppIdle()` primitive is the natural fix.** Once M3 lands, wire it into `gracefulShutdown()` too — same predicate, two consumers. This is a ~1 hour incremental change once M3 exists.

Track as a separate GitHub issue or fold into the same PR.

---

## Session Artifacts (Inventory)

### Ideas generated (60+)
- **Phase 1 (Cross-Pollination):** 15 scoped ideas across 6 clusters (library, download UX, install UX, Linux quirks, project-specific)
- **Phase 2 (Morphological Analysis):** 6 axes × 3-4 options = ~22 structural options, 4 profiles
- **Phase 3 (SCAMPER):** 23 refinements across 7 lenses; ~12 adopted, ~8 considered, 3 rejected
- **Phase 4 (Decision Tree):** 7 milestones with dependency DAG, 6 open decisions (all resolved), 8 risks

### Key breakthroughs
1. **Scope discipline** — user's mid-session correction pulled the design back from architectural wildness (flipping to a server-served web app, P2P distribution, etc.) to the pragmatic "fetch + install from GitHub assets".
2. **One-modal pre-install** ([SCAMP-C1]) — merging release-notes and server-mismatch into a single informed decision point instead of two sequential dialogs.
3. **Idle-queue install** (axis 5 = C) — never block download, defer install to transcription-idle window with user confirmation toast. Better than "block everything" or "silent install".
4. **`manifest.json` unified source of truth** — rolled together D1 (compat range) + D5 (checksums) + future channel/releaseType info into a single ~200-byte CI-published asset.
5. **Found a latent data-loss bug** — `gracefulShutdown()` doesn't check `is_busy`. The update feature's safety primitive naturally fixes it.

---

## Next Steps (Hand-Off to Implementation)

1. **Create GitHub issue** referencing this spec document, broken into M1-M7 sub-issues
2. **Start with M1** (electron-updater wiring) — lowest risk, unlocks everything else
3. **Add CI task** to generate `manifest.json` on release (can be done in parallel with M1)
4. **Invoke** `/bmad-create-story` or `/bmad-quick-dev` passing this document as input when ready to implement

This document is self-contained enough to be the input to a coding agent — no further context needed.
