---
title: 'In-app Update — Remote Host Validation & Install-Gate Fail-Closed'
type: 'bugfix'
created: '2026-04-13'
status: 'done'
baseline_commit: '6044068c9a0cb6f8ffe811b9889edf5f088e4f0c'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When `connection.useRemote=true` but the selected host field is blank (Tailscale `remoteHost` or LAN `lanHost`), `appState.getServerUrl` silently falls back to `'localhost'` at appState.ts:17-19. On a pure-remote machine the probe at `/api/admin/status` fails with `server-unreachable` and `InstallGate.requestInstall` defers the install indefinitely — misleading diagnostic, frozen Install button. LAN mode has a save-time validator at SettingsModal.tsx:410-413; Tailscale mode is unguarded.

**Approach:** Add the symmetric Tailscale save-time validator in `SettingsModal`, AND add a main-process fail-closed predicate so pre-existing bad state (older Dashboard versions, direct electron-store edits, config import) surfaces a diagnostic `remote-host-not-configured` reason instead of misleading `server-unreachable`.

## Boundaries & Constraints

**Always:**
- `isAppIdle()` distinguishes `remote-host-not-configured` from `server-unreachable` so copy and shutdown-dialog suppression decide correctly.
- `getServerUrl` does NOT silently coerce blank remote hosts to `'localhost'` — callers short-circuit on the predicate before URL construction.
- The new reason propagates through `InstallGate.requestInstall`'s `deferred-until-idle` result via `detail`, mirroring the existing `auth-error` path.
- `gracefulShutdown`'s busy-dialog skip-list includes the new reason — can't probe, parity with `server-unreachable`.
- Renderer validator blocks all `api.config.set` writes when Tailscale mode is selected with blank `remoteHost` — same shape as the existing LAN validator.

**Ask First:**
- If the banner UX needs a dedicated `config-required` visual state beyond the existing `ready_blocked` — current scope relies on banner's busy-reason surfacing.

**Never:**
- No runtime auto-repair writing a default `remoteHost` — user config is sacred.
- No new preload/IPC surface — reuse `updates:install` / `getInstallerStatus`.
- No change to `CompatUnknownReason` union — `compatGuard.fetchServerVersion` already fails-open via null-return; short-circuit there is out of scope.
- No change to the `connection.useRemote` toggle UX (e.g. auto-disabling on blank host).

## I/O & Edge-Case Matrix

| Scenario | State | Expected Behavior |
|---|---|---|
| Local mode | `useRemote=false` | `getServerUrl` → `http://<localHost>:<port>`; probe proceeds |
| Configured remote | `useRemote=true`, selected host non-blank | probe proceeds |
| Bug target: blank remote (Tailscale or LAN after `.trim()`) | `useRemote=true`, selected host `''` / whitespace | `isAppIdle` → `{idle:false, reason:'remote-host-not-configured'}`; `InstallGate.requestInstall` → `{ok:false, reason:'deferred-until-idle', detail:'remote-host-not-configured'}`; no fetch leaves main process |
| Save-time Tailscale block | User clicks Save with Tailscale + blank `remoteHost` | Toast `"Tailscale remote mode requires a host or IP address."`; zero `api.config.set` calls |
| Save-time LAN block | (existing) | unchanged |
| Quit with misconfigured remote | Quit triggered, blank host | `gracefulShutdown` skips busy-dialog (parity with `server-unreachable`), proceeds |

</frozen-after-approval>

## Code Map

- `dashboard/electron/appState.ts` — add `isServerUrlConfigured(store)`; `isAppIdle` short-circuits on it; remove `|| 'localhost'` fallback in `useRemote` branch of `getServerUrl`.
- `dashboard/electron/main.ts` (gracefulShutdown ~L1985-2025) — extend busy-dialog skip-list and wait-loop break condition with the new reason.
- `dashboard/components/views/SettingsModal.tsx` (handleSave ~L402-413) — add symmetric Tailscale validator adjacent to existing LAN validator.
- `dashboard/electron/__tests__/appState.test.ts` — coverage for predicate, short-circuit, and `InstallGate` `detail` propagation.
- `dashboard/electron/compatGuard.ts` (fetchServerVersion ~L439) — LEAVE UNCHANGED; already fails-open via null-return + `server-version-unavailable`.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/appState.ts` — Export `isServerUrlConfigured(store: AnyStore): boolean`. Returns `false` when `useRemote=true` AND the active-profile host (`tailscale`→`remoteHost`, `lan`→`lanHost`) is blank after `.trim()`. Returns `true` for local mode and any configured remote. `isAppIdle` calls it first and returns `{idle: false, reason: 'remote-host-not-configured'}` before any `fetch`. Remove the `|| 'localhost'` fallback inside the `useRemote` branch of `getServerUrl`.
- [x] `dashboard/electron/main.ts` — In `gracefulShutdown`: extend `canDialog` (~L1995-2000) to also exclude `idle.reason === 'remote-host-not-configured'`; extend the wait-loop break at ~L2021 to break on the new reason too.
- [x] `dashboard/components/views/SettingsModal.tsx` — In `handleSave`, immediately before the existing LAN validator (line 410): `if (clientSettings.useRemote && normalizedRemoteProfile === 'tailscale' && !normalizedRemoteHost) { toast.error('Tailscale remote mode requires a host or IP address.'); return; }`.
- [x] `dashboard/electron/__tests__/appState.test.ts` — (a) `isServerUrlConfigured` cases: Tailscale-blank, LAN-blank, whitespace-only host, local mode with blank remotes, both configured profiles. (b) `isAppIdle` returns the new reason without invoking the `fetch` mock. (c) `InstallGate.requestInstall` with `idleCheck` returning the new reason resolves with `detail:'remote-host-not-configured'`.

**Acceptance Criteria:**
- Given `useRemote=true` + `remoteProfile=tailscale` + blank `remoteHost`, when the renderer calls `api.install()`, then it resolves `{ok:false, reason:'deferred-until-idle', detail:'remote-host-not-configured'}` with no HTTP request to `/api/admin/status`.
- Given the same invalid config, when the user clicks Save in SettingsModal, then the Tailscale toast appears and no `connection.*` keys are written.
- Given the same invalid config, when quit is triggered, then `gracefulShutdown` skips the busy-dialog and proceeds (parity with `server-unreachable`).
- Given `useRemote=false`, when the user clicks Save with blank remote hosts, then the save proceeds unmodified.
- Given a previously-valid Tailscale config, when the user clears `remoteHost` and clicks Save, then the save is blocked and the stored value is unchanged on next modal open.

## Design Notes

**Why both layers:** save-time validator handles fresh user input; main-process predicate handles bad state reaching the install path via paths that bypass `handleSave` (older Dashboard versions, direct electron-store JSON edits, future config import). Shipping only one leaves a detectable deadlock; shipping both closes it from both ends.

**Why remove the `|| 'localhost'` fallback rather than keep it defensive:** callers now short-circuit on the predicate, making the fallback unreachable on install/shutdown paths. Keeping it would silently re-enable the defect for any future caller that forgets the predicate — defeating the purpose of the fix. Removing it fails loudly on the next forgotten caller (malformed URL → fetch rejection).

**Why compatGuard is untouched:** it already fails-open via null-return + `server-version-unavailable`, which is M4's frozen behavior. Adding the predicate there would flip fail-open to fail-closed — a scope change. Revisit when a compat-UX consumer needs the distinction.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` — expected: clean.
- `cd dashboard && npx vitest run electron/__tests__/appState.test.ts` — expected: existing cases pass plus 3 new cases.
- `cd dashboard && npm run ui:contract:check` — expected: clean (SettingsModal change is logic-only; contract check is the CLAUDE.md invariant).

**Manual checks:**
- Settings → enable "Use remote" → Tailscale profile → blank remote host → Save → toast appears, modal stays open, no `connection.*` writes.
- With invalid config pre-seeded (electron-store edited while app stopped): relaunch → trigger install via banner → deferred; main-process logs show no `/api/admin/status` fetch attempt.
- With invalid config pre-seeded: trigger quit → `gracefulShutdown` proceeds without the busy-dialog.

## Suggested Review Order

**Core design — predicate-first fail-closed**

- Entry point: the new predicate is the single source of truth for "can we probe?"; both install-gate and shutdown gate on it.
  [`appState.ts:43`](../../dashboard/electron/appState.ts#L43)

- `isAppIdle` short-circuits before URL construction — surfaces diagnostic reason, skips the fetch entirely.
  [`appState.ts:73`](../../dashboard/electron/appState.ts#L73)

- Removed the silent `|| 'localhost'` fallback; comment explains the two-path design (install short-circuits, compat fails-open via M4).
  [`appState.ts:17`](../../dashboard/electron/appState.ts#L17)

**Shutdown parity**

- `canDialog` skip-list extended — can't probe means skip the "busy transcription" dialog, parity with `server-unreachable` / `auth-error` / `unknown`.
  [`main.ts:1996`](../../dashboard/electron/main.ts#L1996)

- 120 s wait-loop break extended — same reason, same semantics.
  [`main.ts:2023`](../../dashboard/electron/main.ts#L2023)

**Renderer save-time block**

- Symmetric Tailscale validator mirrors the existing LAN one; closes the "new user persists bad state" path the main-process predicate can't catch upstream.
  [`SettingsModal.tsx:410`](../../dashboard/components/views/SettingsModal.tsx#L410)

**Test coverage**

- Predicate truth table: local/Tailscale/LAN × blank/whitespace/configured.
  [`appState.test.ts:207`](../../dashboard/electron/__tests__/appState.test.ts#L207)

- `isAppIdle` short-circuit asserts `fetch` never invoked.
  [`appState.test.ts:315`](../../dashboard/electron/__tests__/appState.test.ts#L315)

- `InstallGate` `detail` propagation asserts the reason reaches the renderer through the existing channel.
  [`appState.test.ts:404`](../../dashboard/electron/__tests__/appState.test.ts#L404)

- Regression lock: `getServerUrl` no longer coerces blank-remote to localhost — catches any future refactor that reintroduces the fallback.
  [`appState.test.ts:197`](../../dashboard/electron/__tests__/appState.test.ts#L197)
