---
title: 'GH #124 — Metal-start failure diagnostics + thin-DMG detection + CI venv gate'
type: 'bugfix'
created: '2026-05-31'
status: 'done'
baseline_commit: '9af6ac56455675edf75bfae196cd2d314d0b82b5'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** On macOS (Apple Silicon), "Start Metal Server" fails with *"Cannot find uvicorn binary. Run `uv sync --extra mlx`…"* (GH #124, "worked in 1.3.3"). This is **not** a code/build regression — `_resolveUvicornPath()` is byte-identical across v1.3.3→v1.3.5 and both metal DMGs were built correctly (verified from CI logs). The cause is environmental: the user most likely installed the **thin** `-arm64-mac.dmg` (dashboard-only, no backend) instead of `-arm64-mac-metal.dmg`, or a manual swap lost the venv. The current message is developer-only and useless to end users, and the throw happens *before* any log line, so the Metal log panel is empty (symptom 3).

**Approach:** Make the failure self-explaining instead of changing the (correct) resolution logic. (A) Replace the bare throw with an environment-aware diagnostic that detects thin-vs-metal DMG and names the exact artifact to reinstall; (B) route the diagnostic through the existing MLX log sink (disk + panel) *before* throwing. Add a CI gate so a broken bundle can never ship silently again.

## Boundaries & Constraints

**Always:** Keep the existing two-candidate resolution order and the `python -m uvicorn` spawn unchanged. The thrown `Error.message` is the user-facing string (it already propagates to `ServerView` `toast.error`) — make its first sentence actionable. Gate the "thin DMG" branch on `app.isPackaged` so dev machines (which also set `process.resourcesPath`) are never misclassified. Log every diagnostic line via `_appendLog(...)` before throwing.

**Ask First:** Adding a self-healing python-direct fallback (resolving the `.venv` dir and spawning `python -m uvicorn` even when `bin/uvicorn` is absent). Changing the CI venv-injection recipe, uv/CPython pins, or symlink logic.

**Never:** Do not edit `_resolveUvicornPath` candidate paths or the build recipe (`uv sync`, `cp -a`, symlink rewrite) — both are proven correct. Do not touch the renderer toast. Do not address idle CPU/GPU (symptom 2 — deferred to #87) or diarization (#88 — unblocked automatically). Do not revert `a129877`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | `app.isPackaged`, `<resources>/backend/.venv/bin/uvicorn` exists | Resolution succeeds; server spawns; status → starting→running (unchanged) | N/A |
| Thin DMG | `app.isPackaged`, `<resources>/backend` does NOT exist | Throw + log: "dashboard-only build … download TranscriptionSuite-`<version>`-arm64-mac-metal.dmg and reinstall" | Diagnostic appended to sink (disk+panel) AND thrown → toast; status=error |
| Corrupted metal venv | `app.isPackaged`, `<resources>/backend` exists but `.venv/bin/uvicorn` missing | Throw + log: "Metal backend installed but Python env incomplete … reinstall from …-metal.dmg" + probed paths | same |
| Dev, venv not built | not packaged, no `server/backend/.venv/bin/uvicorn` | Throw + log: "Run `uv sync --extra mlx` inside server/backend first" + probed paths | same |
| CI broken bundle | bundled venv missing `bin/uvicorn` OR bundled python can't `import uvicorn` | `build-macos-metal` job FAILS (exit 1) before DMG | `::error::` annotation |

</frozen-after-approval>

## Code Map

- `dashboard/electron/mlxServerManager.ts` -- `start()` throw at L63-70; `_resolveUvicornPath()` L299-317 (two candidates: dev `<appDir>/../server/backend/.venv/bin/uvicorn`, packaged `<resources>/backend/.venv/bin/uvicorn`); `_appendLog()` L331-345 (ring + sink→disk). Edit site for A+B.
- `dashboard/electron/mlxLogSink.ts` -- sink that persists to `mlx-server.log` + buffers until renderer ready; already injected (no change, just relied upon).
- `dashboard/components/views/ServerView.tsx:667,886` -- `toast.error(\`Failed to start Metal server: ${msg}\`)` consumes the thrown message verbatim (no change needed).
- `.github/workflows/release.yml:191-235` -- `build-macos-metal` venv-injection step; L239-265 re-sign; L267 DMG. Add gate after re-sign.
- `dashboard/electron/__tests__/mlxServerManager.test.ts` -- existing vitest harness (mocks `fs`, `electron.app`, `child_process`). Extend for new cases.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/mlxServerManager.ts` -- Replace the L63-70 null-check/throw: extract `_uvicornCandidates(): string[]` (the current candidate list), resolve via `candidates.find(c => fs.existsSync(c))`; on miss, build a message via new `_diagnoseMissingUvicorn(candidates)` using `app.isPackaged` + `process.resourcesPath` + `app.getVersion()` (thin-DMG vs corrupted-venv vs dev branches per matrix); `_appendLog('[MLX] ' + line)` for each message line **before** `_setStatus('error')`/emit/`throw new Error(message)`. -- self-explaining failure + non-empty Metal log (symptoms 1 & 3).
- [x] `.github/workflows/release.yml` -- After "Re-sign app bundle…" (L265), before "Create DMG" (L267), add step "Verify bundled MLX venv": `test -e "$VENV_DIR/bin/uvicorn"` and `"$VENV_DIR/bin/python3" -c "import uvicorn"`, each failing the job with `::error::` on miss. -- prevents silent broken-bundle releases.
- [x] `dashboard/electron/__tests__/mlxServerManager.test.ts` -- Add cases for thin-DMG, corrupted-venv, and dev messages; assert the diagnostic is appended to the ring (`getLogs()`) / sink before the throw. Extend the `electron` mock with `isPackaged` + `getVersion: () => '1.3.5'`; set/restore `process.resourcesPath` per case. -- locks the I/O matrix.

**Acceptance Criteria:**
- Given a thin (dashboard-only) install, when "Start Metal Server" is clicked, then the toast and the Metal log both name `TranscriptionSuite-<version>-arm64-mac-metal.dmg` to download — not the developer `uv sync` instruction — and `mlx:getLogs` returns the diagnostic lines.
- Given any uvicorn-resolution miss, when `start()` fails, then the diagnostic is appended to the MLX sink (persisted to `mlx-server.log`, visible in the Metal log panel) before the `Error` is thrown.
- Given a correctly bundled metal DMG, when `start()` runs, then resolution succeeds and lifecycle behavior is unchanged.
- Given a release build whose bundled venv lacks a runnable uvicorn, when `build-macos-metal` runs, then the job fails with `::error::` and publishes no DMG.

## Design Notes

Message-only fix is deliberate: the adversarial investigation pulled both releases' CI logs (runs `24623104711` / `25390150440`) and falsified the "build silently shipped a broken venv (uv/CPython drift)" theory — identical CPython 3.13.13, same `setup-uv@v4` SHA, uvicorn present, 1.6 GB bundles. So the fix targets diagnostics + a prevention gate, never the resolver/recipe.

Golden message (thin DMG):
```
This is the dashboard-only build — it does not include the Metal (MLX) Python
backend, so the Metal server cannot start. Download
"TranscriptionSuite-1.3.5-arm64-mac-metal.dmg" (the build whose name ends in
"-metal") and reinstall.
Checked: /Applications/…/Resources/backend (not found).
```

## Verification

**Commands:**
- `cd dashboard && npx vitest run electron/__tests__/mlxServerManager.test.ts` -- expected: all pass incl. new thin-DMG / corrupted-venv / dev cases.
- `cd dashboard && npm run typecheck` -- expected: no TS errors.
- `actionlint .github/workflows/release.yml` (if installed) -- expected: clean; else inspect the new step's YAML/shell manually.

**Manual checks (if no CLI):**
- Read the new `release.yml` step: confirm it runs after re-sign, before DMG creation, and exits non-zero on either assertion failure.

## Suggested Review Order

**The diagnostic (design intent)**

- Entry point — the three-way classification (thin-DMG vs corrupted-venv vs dev) replacing the developer-only error
  [`mlxServerManager.ts:335`](../../dashboard/electron/mlxServerManager.ts#L335)

- Intel/x64 branch — never sends an Apple-Silicon-only DMG to a Mac that cannot run MLX (review finding)
  [`mlxServerManager.ts:355`](../../dashboard/electron/mlxServerManager.ts#L355)

- Version resolved defensively — a damaged bundle's `getVersion()` throw must not mask the diagnostic
  [`mlxServerManager.ts:394`](../../dashboard/electron/mlxServerManager.ts#L394)

- Resolver split into a candidate-list builder; resolution order + `python -m uvicorn` spawn unchanged
  [`mlxServerManager.ts:309`](../../dashboard/electron/mlxServerManager.ts#L309)

**Surfacing the failure (symptom 3 — empty logs)**

- Full diagnostic logged to the sink/disk BEFORE throwing; only the single-line headline is thrown to the toast
  [`mlxServerManager.ts:72`](../../dashboard/electron/mlxServerManager.ts#L72)

**CI prevention gate**

- Fails the release if the bundled venv lacks a runnable uvicorn/fastapi — after re-sign, before DMG
  [`release.yml:267`](../../.github/workflows/release.yml#L267)

**Tests (peripheral)**

- Seven edge-case tests locking the message branches + before-throw logging/status
  [`mlxServerManager.test.ts:269`](../../dashboard/electron/__tests__/mlxServerManager.test.ts#L269)

- Intel-misdirection regression guard
  [`mlxServerManager.test.ts:313`](../../dashboard/electron/__tests__/mlxServerManager.test.ts#L313)
