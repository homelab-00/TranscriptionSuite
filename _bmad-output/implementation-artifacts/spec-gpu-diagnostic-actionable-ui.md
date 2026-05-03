---
title: 'GPU Diagnostic — actionable UI (open log + per-warning hints)'
type: 'feature'
created: '2026-04-29'
status: 'done'
baseline_commit: '42a07231791722de1dca3ea5efa204bce6187d4a'
context:
  - '{project-root}/scripts/diagnose-gpu.sh'
  - '{project-root}/scripts/README-gpu-diagnostic.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When the user clicks "Run Full Diagnostic" on the GPU Health card, the dashboard fires `scripts/diagnose-gpu.sh` and surfaces only a `window.alert` with the log path and a `tail -f` hint. Two friction points: (1) the user must hunt the log path in their file manager / terminal to read it, and (2) actionable WARN findings (e.g. `#4 CDI spec is older than driver modules — regenerate with: sudo nvidia-ctk cdi generate ...`) are buried inside the log instead of being raised to the UI surface.

**Approach:** Wait for the diagnostic script to finish, parse its log into a structured summary (counts + per-check `[WARN]`/`[FAIL]` rows with extracted "regenerate with:" / "fix:" commands), and render that summary in a new `GpuDiagnosticModal`. The modal exposes (a) an **Open Log** button that calls the existing `electronAPI.app.openPath` IPC (Electron's `shell.openPath`) so the file opens in the OS default text editor, (b) a **Copy Path** button, and (c) a copyable command per actionable WARN/FAIL row. No `sudo` is run from the dashboard — copy-paste only, matching PR #107's advisor-not-agent stance.

## Boundaries & Constraints

**Always:**
- Reuse the existing `app:openPath` IPC; do not add new shell-execution privilege surfaces.
- Keep all diagnostic command commands copy-only; never spawn `sudo`.
- Preserve the diagnostic log on disk at the current per-user `userData/gpu-diagnostics/` location — do not change the log path or permissions (0o700 dir, 0o600 file, random suffix; closes the CodeQL `js/insecure-temporary-file` finding).
- Card stays NVIDIA-only, hidden on macOS / non-NVIDIA Linux / Windows (existing `gpuDetected` gate in `GpuHealthCard`).
- Frozen-block log line shape (`[STATUS] #N  title  detail`) — parser must tolerate variable whitespace, missing detail, and lines that wrap due to long `detail` text.

**Ask First:**
- If the parser cannot find the canonical Summary section in the log, do we (a) still show the modal with raw counts of `[WARN]/[FAIL]` lines we counted ourselves, or (b) fall back to the old `alert` flow? Default proposed: (a).

**Never:**
- Do not auto-run `nvidia-ctk cdi generate` or any other fix from the dashboard.
- Do not introduce `child_process.exec` with shell strings; keep `spawn(['bash', scriptPath])`.
- Do not block the UI while the script runs longer than ~2s without a spinner / progressive feedback.
- Do not change the bash script's exit semantics (still exits 0 on WARN, non-zero only on FAIL — matches `scripts/README-gpu-diagnostic.md`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Linux + NVIDIA, all PASS | script exits 0, log has `PASS: 11 WARN: 0 FAIL: 0` | Modal: green summary, no rows, **Open Log** + **Copy Path** + **Close** | N/A |
| Stale CDI (real user repro) | `[WARN] #4 CDI spec vs driver mtime ... regenerate with: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` | Modal lists row "CDI spec vs driver mtime — your CDI spec is older than driver, please regenerate with:" + copyable `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` | N/A |
| Multiple WARN/FAIL | log has several `[WARN]`/`[FAIL]` lines | All listed; rows without an extractable command render the raw `detail` text; rows with one render `CopyableCommand` underneath | N/A |
| Script missing | `runGpuDiagnostic` returns `script-missing` | Modal in degraded mode: shows `manualCommand` as copyable; no log path, no warnings, **Open Log** hidden | N/A |
| Non-Linux host | `runGpuDiagnostic` returns `unsupported` | Modal not opened — show inline toast "GPU diagnostic is for Linux NVIDIA hosts only" | N/A |
| `app.openPath` returns non-empty error string | OS has no associated app for `.log` | Toast with the returned error string; **Copy Path** still works | Toast, no crash |
| Log read fails (race / permission) | script exited but `fs.readFile` rejects | Modal opens with `Open Log` + `Copy Path` only, no parsed summary, sub-headline "Could not parse log — open it manually." | Logged to console, modal still useful |
| Script exit non-zero (FAIL count > 0) | exit code ≠ 0 | Same modal, summary banner red instead of green/amber | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts` -- extend `RunGpuDiagnosticResult`; convert `runGpuDiagnostic` to async; add `parseDiagnosticLog(content)` pure helper exported for tests.
- `dashboard/electron/preload.ts` -- update `runGpuDiagnostic` return type signature in the `electronAPI` declaration block (lines ~140-158).
- `dashboard/components/views/GpuDiagnosticModal.tsx` -- new component (mirrors UpdateModal lifecycle: double-RAF entry + 500ms exit, `aria-modal="true"`, click-outside-to-close).
- `dashboard/components/views/ServerView.tsx` -- replace `handleRunGpuDiagnostic` body: render `<GpuDiagnosticModal>` controlled by `diagnosticState` (`'idle' | 'running' | 'open'`).
- `dashboard/components/views/GpuHealthCard.tsx` -- no API change; `onRunDiagnostic` still fires; spinner state surfaced via new optional `running?: boolean` prop driving Button `disabled` + label "Running…".
- `dashboard/electron/__tests__/dockerManagerGpuDiagnostic.test.ts` -- new file: `parseDiagnosticLog` table-driven cases (happy / stale-CDI / multi-warn / no-summary / mixed-status).
- `dashboard/components/views/__tests__/GpuDiagnosticModal.test.tsx` -- new file: renders summary, surfaces stale-CDI hint with command, **Open Log** button calls `electronAPI.app.openPath`.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/dockerManager.ts` -- extract `parseDiagnosticLog(content: string): DiagnosticSummary` (pure, exported). Convert `runGpuDiagnostic` to `Promise<RunGpuDiagnosticResult>`: redirect script stdio to log fd, wait for `child` `exit` event, `fs.promises.readFile` the log, call `parseDiagnosticLog`, return enriched `{status: 'completed', logPath, summary, exitCode}`. Keep `'started'/'unsupported'/'script-missing'` paths intact (no log to read for the latter two).
- [x] `dashboard/electron/__tests__/dockerManagerGpuDiagnostic.test.ts` -- pure-function tests for the parser covering every row in I/O Matrix.
- [x] `dashboard/electron/preload.ts` -- update `runGpuDiagnostic` return type union to include the new `'completed'` branch with `summary`, `exitCode`. No runtime change.
- [x] `dashboard/components/views/GpuDiagnosticModal.tsx` -- new modal. Props: `{ isOpen, result, onClose }`. Renders summary chips (green / amber / red counts), per-issue rows with title + detail + optional `<CopyableCommand cmd={...}>`, footer: **Open Log** → `electronAPI.app.openPath(logPath)`, **Copy Path** (reuses `writeToClipboard`), **Close**. Hide **Open Log** when no `logPath`.
- [x] `dashboard/components/views/__tests__/GpuDiagnosticModal.test.tsx` -- (a) renders the stale-CDI WARN row with the regenerate command visible, (b) clicking **Open Log** calls `electronAPI.app.openPath` with the supplied path, (c) `script-missing` result still renders manual command and hides **Open Log**.
- [x] `dashboard/components/views/ServerView.tsx` -- replace `handleRunGpuDiagnostic` body with state machine: set `running`, await IPC, set result + `open: true`, render `<GpuDiagnosticModal />` near other modals. Keep `unsupported` toast path. Pass `running` to `<GpuHealthCard onRunDiagnostic running={diagnosticRunning}/>`.
- [x] `dashboard/components/views/GpuHealthCard.tsx` -- accept optional `running?: boolean`; when true, `Button` disabled + label "Running diagnostic…".
- [x] `dashboard/ui-contract/transcription-suite-ui.contract.yaml` -- bump `spec_version` to 1.0.32 + rebuild + relock baseline (new utility classes from `GpuDiagnosticModal`; review-patch removed `#107` PR reference from a ServerView comment that the scanner had been picking up as a hex color).

**Acceptance Criteria:**
- Given a Linux+NVIDIA host where the diagnostic emits the stale-CDI WARN, when the user clicks **Run Full Diagnostic**, then the modal opens with a row titled "CDI spec vs driver mtime" containing the verbatim message "CDI spec is older than driver modules — regenerate with: …" and a copyable `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml` command.
- Given the modal is open with a successful diagnostic, when the user clicks **Open Log**, then `window.electronAPI.app.openPath` is called exactly once with the absolute log path returned by the IPC.
- Given the script writes to `userData/gpu-diagnostics/`, when a second diagnostic runs in the same second, then the random-suffix filename rule keeps the new log distinct (regression on PR #107 invariant — covered by parser test using two distinct paths).
- Given a non-Linux host, when the user clicks **Run Full Diagnostic**, then no modal opens and a toast surfaces "GPU diagnostic is for Linux NVIDIA hosts only".
- Given the parser cannot find a Summary block, when the modal renders, then it shows a "Could not parse log — open it manually." sub-headline AND **Open Log** + **Copy Path** still work.

## Spec Change Log

### 2026-04-29 — review patches (iteration 1)

- **Trigger:** code-reviewer agent flagged (HIGH) fd-leak on `child.error` path in `runGpuDiagnostic` and (HIGH) brittleness in the regex comment vs implementation, plus (MEDIUM) `#107` polluting the contract palette.
- **Amended:** none — these are `patch`-class findings, fixed in code without changing the spec.
- **Known-bad state avoided:** (a) Electron main-process fd leaks accumulating after every diagnostic-script-not-found click; (b) future maintainer "fixing" the regex per the misleading comment and breaking multi-word title parsing; (c) ServerView comment text bleeding into the UI contract literal-palette and triggering false drift.
- **KEEP instructions for re-derivation:** the `\s{2,}` separator in `DIAG_ROW_RE` is intentional — `\s+` would let the lazy title group stop at the first internal space and break titles like "/dev/char NVIDIA symlinks". The 50-char-exact title case is genuinely unreachable from the current bash script (max title is ~36 chars). Do not change the regex without proving the script can produce a 50-char title.

## Design Notes

**Parser regex shape (illustrative, ≤8 lines):**
```ts
// Each check line: "[STATUS] #N  Title (≤50 col)  detail"
const ROW_RE = /^\[(PASS|WARN|FAIL|INFO)\]\s+#(\d+)\s+(.+?)\s{2,}(.*)$/;
const CMD_RE = /\b(?:regenerate with|fix):\s+(.+?)\s*(?:\(|$)/i;
const SUMMARY_RE = /^PASS:\s*(\d+)\s+WARN:\s*(\d+)\s+FAIL:\s*(\d+)\s*$/m;
// CMD_RE is greedy enough for "sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
// but stops at " (also add udev rule…)" parentheticals.
```
The parser exists as a pure function so it can be unit-tested without spawning bash or reading from disk.

**Why a modal vs. expanding the card in place:** the diagnostic body is long (3-line summary + up to 11 rows + log path). Inlining bloats the Server tab vertically and would force scroll-jumps when the diagnostic finishes. A modal keeps the Server tab layout stable and gives selectable text on KDE Wayland (the dev host's primary platform) where `window.alert` doesn't always allow text selection — addressing the same UX gap the PR #107 description explicitly listed as a follow-up.

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/dockerManagerGpuDiagnostic.test.ts components/views/__tests__/GpuDiagnosticModal.test.tsx components/views/__tests__/GpuHealthCard.test.tsx` -- expected: all green, parser table cases pass, modal renders stale-CDI row with command.
- `cd dashboard && npx vitest run` -- expected: full suite green (PR #107 baseline was 986 / 53 files).
- `cd dashboard && npx tsc --noEmit` -- expected: clean (no new type errors from the union-extended return).
- `cd dashboard && npm run ui:contract:check` -- expected: 16/16 pass; if the modal introduces new selectors, run the full update sequence (`extract` → `build` → `--update-baseline` → `check`).

**Manual checks:**
- On the dev host (Linux + NVIDIA, currently shows WARN #4): launch the dashboard, click **Run Full Diagnostic**, confirm the modal lists the stale-CDI hint with the copy button. Click **Open Log** and confirm the system default text editor opens the file.
- Force `script-missing` by renaming `scripts/diagnose-gpu.sh`: confirm modal shows manual command, **Open Log** hidden.

## Suggested Review Order

**Parser & async runner (the new shape of the IPC contract)**

- Pure log parser — read this first to grasp the data flow into the modal.
  [`dockerManager.ts:407`](../../dashboard/electron/dockerManager.ts#L407)

- Async refactor of `runGpuDiagnostic` with fd-leak-safe spawn cleanup.
  [`dockerManager.ts:451`](../../dashboard/electron/dockerManager.ts#L451)

- Renderer-side type for the new IPC return shape.
  [`preload.ts:153`](../../dashboard/electron/preload.ts#L153)

**UI surface (replaces window.alert)**

- New modal — Open Log button calls existing `electronAPI.app.openPath`.
  [`GpuDiagnosticModal.tsx:120`](../../dashboard/components/views/GpuDiagnosticModal.tsx#L120)

- ServerView state machine: running/result/open + spinner-disable.
  [`ServerView.tsx:1225`](../../dashboard/components/views/ServerView.tsx#L1225)

- GpuHealthCard: `running` prop + button label/disabled binding.
  [`GpuHealthCard.tsx:155`](../../dashboard/components/views/GpuHealthCard.tsx#L155)

**Tests**

- Parser table cases including the multi-word title regression.
  [`dockerManagerGpuDiagnostic.test.ts:1`](../../dashboard/electron/__tests__/dockerManagerGpuDiagnostic.test.ts#L1)

- Modal rendering, Open Log click, script-missing hide path.
  [`GpuDiagnosticModal.test.tsx:1`](../../dashboard/components/views/__tests__/GpuDiagnosticModal.test.tsx#L1)

