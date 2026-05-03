---
title: 'Remote Server TLS Profile Chooser Dialog'
slug: 'remote-tls-profile-chooser'
created: '2026-03-23'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: [React, TypeScript, Electron, electron-store]
files_to_modify:
  - dashboard/electron/dockerManager.ts
  - dashboard/electron/main.ts
  - dashboard/electron/preload.ts
  - dashboard/App.tsx
  - docs/README.md
  - docs/README_DEV.md
code_patterns:
  - Promise-based modal pattern (ref resolver + state toggle)
  - IPC handler pattern (ipcMain.handle + preload bridge + renderer call)
  - Inline modal JSX in App.tsx (not separate component files)
  - electron-store dot-notation keys
test_patterns:
  - Vitest + @testing-library/react for frontend
  - No existing tests for onboarding modals (inline in App.tsx)
---

# Tech-Spec: Remote Server TLS Profile Chooser Dialog

**Created:** 2026-03-23

## Overview

### Problem Statement

When a user clicks "Start Server (Remote Mode)", the app defaults to the Tailscale TLS profile (`connection.remoteProfile = 'tailscale'`). The `resolveTlsCertPaths()` function then looks for Tailscale certificate files at `~/.config/Tailscale/my-machine.crt`. If these don't exist (because the user doesn't use Tailscale), the app throws an immediate error with no opportunity for the user to select the LAN profile instead — which would auto-generate self-signed certificates and "just work."

This affects all users who want remote mode for LAN-only access (GH Issue #43).

### Solution

Intercept the remote-mode startup flow *before* `resolveTlsCertPaths()` is called. When the profile is still the default `'tailscale'` AND the Tailscale cert files don't exist on disk, show a React modal dialog asking the user to choose their remote connection type (Tailscale or LAN). Persist the choice to the existing `connection.remoteProfile` store key, then resume the container start. If the user chooses Tailscale and certs are still missing, show the existing error message with setup instructions.

### Scope

**In Scope:**
- React modal dialog with Tailscale/LAN choice, shown before container start
- Cert file existence check (via IPC) to decide whether to show the dialog
- Persist choice to existing `connection.remoteProfile` electron-store key
- Resume container start after user selection
- README end-user documentation of the remote profile chooser
- README_DEV technical documentation of the flow

**Out of Scope:**
- Changing the default profile value in store defaults
- Adding a "reset profile" UI element
- Auto-generating Tailscale certificates
- Modifying the existing Settings → Connection UI
- Any server-side (Python/FastAPI) changes

## Context for Development

### Codebase Patterns

**Modal pattern (App.tsx):** All onboarding/prompt modals use a consistent Promise-based resolver pattern:
1. A `useState` boolean controls modal visibility (e.g., `hfPromptOpen`)
2. A `useRef` holds a Promise resolver function (e.g., `hfResolverRef`)
3. A `request*` callback opens the modal and returns a Promise
4. A `resolve*` callback closes the modal and resolves the Promise
5. The `startServerWithOnboarding` flow `await`s the request, blocking until the user responds
6. A cleanup `useEffect` resolves any pending Promises on unmount

**Modal JSX (App.tsx):** Modals are rendered inline at the bottom of the App component's JSX, using:
- `{stateVar && (<div className="fixed inset-0 z-60 ...">` pattern
- Outer backdrop div with `bg-black/60 backdrop-blur-sm`
- Inner content div with `rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl`
- Header: `border-b border-white/10 bg-white/5 px-6 py-4`
- Body: `custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6`
- Footer: `border-t border-white/10 bg-white/5 px-6 py-4` with Cancel + primary action buttons
- `Button` component with `variant="ghost"` for cancel, `variant="primary"` for action

**IPC pattern (main.ts → preload.ts → renderer):**
1. `ipcMain.handle('docker:<name>', handler)` in main.ts
2. `<name>: () => ipcRenderer.invoke('docker:<name>')` in preload.ts docker object
3. `(window as any).electronAPI.docker.<name>()` in renderer

**Store pattern:** Uses dot-notation keys like `connection.remoteProfile` with `getConfig`/`setConfig` helpers from `src/config/store.ts`.

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `dashboard/App.tsx:100-227` | Existing modal state, refs, request/resolve callbacks |
| `dashboard/App.tsx:273-519` | `startServerWithOnboarding()` — insertion point for profile check |
| `dashboard/App.tsx:626-742` | Existing modal JSX (model onboarding, dependency install) — template for new modal |
| `dashboard/electron/dockerManager.ts:225-235` | `readRemoteTlsProfile()` — reads store, defaults to `'tailscale'` |
| `dashboard/electron/dockerManager.ts:449-606` | `resolveTlsCertPaths()` — cert resolution + validation logic |
| `dashboard/electron/dockerManager.ts:1066-1076` | `startContainer()` — where `resolveTlsCertPaths()` is called for remote mode |
| `dashboard/electron/main.ts:876-960` | IPC handler registrations for docker operations |
| `dashboard/electron/preload.ts:262-290` | Preload bridge for docker IPC |
| `dashboard/src/config/store.ts:21-22` | `connection.remoteProfile` type definition |
| `dashboard/components/views/SettingsModal.tsx:940-974` | Existing remote profile selector UI (for reference) |
| `docs/README.md:229-397` | Section 3: Remote Connection (where to add user docs) |
| `docs/README_DEV.md:24-38,516-523,724-740` | Remote/TLS sections (where to add dev docs) |

### Technical Decisions

- **React modal over Electron dialog**: Consistent with existing app modals (e.g., model onboarding, HF token, dependency install)
- **No new store key**: Reuse `connection.remoteProfile` — the dialog's purpose is to set this value explicitly when it's still the default
- **Trigger condition**: `profile === 'tailscale'` (default) AND Tailscale cert files don't exist on disk — this avoids showing the dialog to Tailscale users who have valid certs
- **Post-choice behavior**: If Tailscale chosen but certs missing, the existing `resolveTlsCertPaths()` error fires with instructions. If LAN chosen, `resolveTlsCertPaths()` auto-generates self-signed certs (existing behavior)
- **New IPC handler needed**: `docker:checkTailscaleCertsExist` — the renderer cannot access `fs` directly; needs main process to check if cert files exist at the Tailscale default paths. This handler should reuse the same config.yaml path resolution logic as `resolveTlsCertPaths()` (extract `host_cert_path`/`host_key_path`, expand tilde, check `fs.existsSync`)
- **Check placement**: In `startServerWithOnboarding()` (App.tsx), *before* the `docker.startContainer()` call at line 499, matching the pattern of other pre-start checks (model onboarding, HF token, dependency install)

## Implementation Plan

### Tasks

- [x] **Task 1: Add `checkTailscaleCertsExist()` function to dockerManager.ts**
  - File: `dashboard/electron/dockerManager.ts`
  - Action: Add a new exported function `checkTailscaleCertsExist(): boolean` near `resolveTlsCertPaths()` (around line 607). This function should:
    1. Call `readRemoteTlsProfile()` — if result is `'lan'`, return `true` (not relevant, skip dialog)
    2. Read config.yaml using the same `userConfigPath` + `templateCandidates` logic as `resolveTlsCertPaths()` (lines 457-478)
    3. Extract `host_cert_path` and `host_key_path` using `extractYamlScalar()` (lines 486-488)
    4. If either path is unset, return `false`
    5. Expand tilde via `expandTilde()`, then check `fs.existsSync()` for both
    6. Return `true` only if both files exist
  - Notes: Reuses existing helpers (`readRemoteTlsProfile`, `extractYamlScalar`, `expandTilde`). Consider extracting the shared config.yaml reading logic into a small helper to avoid duplication with `resolveTlsCertPaths()`, but only if it doesn't over-complicate things.

- [x] **Task 2: Register IPC handler in main.ts**
  - File: `dashboard/electron/main.ts`
  - Action: Add a new `ipcMain.handle` registration near the other docker handlers (around line 960):
    ```typescript
    ipcMain.handle('docker:checkTailscaleCertsExist', () => {
      return dockerManager.checkTailscaleCertsExist();
    });
    ```
  - Notes: Follows the exact same pattern as `docker:checkGpu` (line 889). No arguments needed.

- [x] **Task 3: Expose IPC in preload.ts**
  - File: `dashboard/electron/preload.ts`
  - Action: Add to the `docker` object in the preload bridge (around line 290):
    ```typescript
    checkTailscaleCertsExist: () =>
      ipcRenderer.invoke('docker:checkTailscaleCertsExist') as Promise<boolean>,
    ```
  - Notes: Follows existing pattern. Returns `Promise<boolean>`.

- [x] **Task 4: Add modal state, refs, and request/resolve callbacks in App.tsx**
  - File: `dashboard/App.tsx`
  - Action: Add the following near the existing modal state declarations (around line 124):
    1. State: `const [remoteProfilePromptOpen, setRemoteProfilePromptOpen] = useState(false);`
    2. Ref: `const remoteProfileResolverRef = useRef<((result: { action: 'cancel' | 'continue'; profile: 'tailscale' | 'lan' }) => void) | null>(null);`
    3. Resolve callback (modeled on `resolveModelOnboarding`):
       ```typescript
       const resolveRemoteProfilePrompt = useCallback(
         (result: { action: 'cancel' | 'continue'; profile: 'tailscale' | 'lan' }) => {
           setRemoteProfilePromptOpen(false);
           const resolver = remoteProfileResolverRef.current;
           remoteProfileResolverRef.current = null;
           resolver?.(result);
         },
         [],
       );
       ```
    4. Request callback (modeled on `requestModelOnboarding`):
       ```typescript
       const requestRemoteProfilePrompt = useCallback(
         async (): Promise<{ action: 'cancel' | 'continue'; profile: 'tailscale' | 'lan' }> => {
           return new Promise((resolve) => {
             remoteProfileResolverRef.current = resolve;
             setRemoteProfilePromptOpen(true);
           });
         },
         [],
       );
       ```
    5. Add cleanup to the existing unmount `useEffect` (around line 210-226):
       ```typescript
       if (remoteProfileResolverRef.current) {
         remoteProfileResolverRef.current({ action: 'cancel', profile: 'tailscale' });
         remoteProfileResolverRef.current = null;
       }
       ```
  - Notes: Follows the exact same pattern as the 3 existing modals.

- [x] **Task 5: Add profile check logic to `startServerWithOnboarding()` in App.tsx**
  - File: `dashboard/App.tsx`
  - Action: Insert the remote profile check in `startServerWithOnboarding()`, just before the `docker.startContainer()` call (before line 499). This should go after all existing onboarding checks (model, dependency, HF token) and before the container start:
    ```typescript
    // --- Remote profile chooser (GH #43) ---
    if (mode === 'remote') {
      const dockerApi = (window as any).electronAPI?.docker;
      const certsExist = await dockerApi?.checkTailscaleCertsExist?.().catch(() => false);
      const currentProfile = await getConfig<'tailscale' | 'lan'>('connection.remoteProfile');
      if (currentProfile !== 'lan' && !certsExist) {
        const profileResult = await requestRemoteProfilePrompt();
        if (profileResult.action === 'cancel') return;
        await setConfig('connection.remoteProfile', profileResult.profile);
      }
    }
    ```
  - Notes: The `dockerApi` variable already exists in scope (line 294). The `currentProfile !== 'lan'` check ensures the dialog is skipped if the user previously chose LAN. The `!certsExist` check ensures it's skipped if Tailscale certs are in place. Add `requestRemoteProfilePrompt` to the `useCallback` dependency array (line 518).

- [x] **Task 6: Add modal JSX in App.tsx**
  - File: `dashboard/App.tsx`
  - Action: Add the modal JSX after the existing modals (after the `hfPromptOpen` modal, around line 800+). Follow the exact same structure as the `dependencyInstallPromptOpen` modal (lines 707-742) for consistency:
    ```tsx
    {remoteProfilePromptOpen && (
      <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
        <div
          className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ease-in-out"
          onClick={() => resolveRemoteProfilePrompt({ action: 'cancel', profile: 'tailscale' })}
        />
        <div className="relative flex w-full max-w-lg flex-col overflow-hidden rounded-3xl border border-white/10 bg-black/60 shadow-2xl backdrop-blur-xl transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]">
          <div className="flex flex-none items-center justify-between border-b border-white/10 bg-white/5 px-6 py-4 select-none">
            <h2 className="text-lg font-semibold text-white">Remote Connection Profile</h2>
          </div>
          <div className="custom-scrollbar selectable-text flex-1 overflow-y-auto bg-black/20 p-6">
            <div className="space-y-4 text-sm text-slate-300">
              <p>How will remote clients connect to this server?</p>
              <div className="space-y-3">
                <button
                  className="w-full rounded-xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-white/20 hover:bg-white/10"
                  onClick={() => resolveRemoteProfilePrompt({ action: 'continue', profile: 'lan' })}
                >
                  <div className="font-medium text-white">LAN (local network)</div>
                  <div className="mt-1 text-xs text-slate-400">
                    Both machines on the same network. A self-signed TLS certificate is generated automatically.
                  </div>
                </button>
                <button
                  className="w-full rounded-xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-white/20 hover:bg-white/10"
                  onClick={() => resolveRemoteProfilePrompt({ action: 'continue', profile: 'tailscale' })}
                >
                  <div className="font-medium text-white">Tailscale</div>
                  <div className="mt-1 text-xs text-slate-400">
                    Cross-network access via Tailscale. Requires Tailscale certificates (see README for setup).
                  </div>
                </button>
              </div>
              <p className="text-xs text-slate-500">
                You can change this later in Settings &rarr; Client &rarr; Remote Profile.
              </p>
            </div>
          </div>
          <div className="flex flex-none justify-end gap-3 border-t border-white/10 bg-white/5 px-6 py-4 select-none">
            <Button
              variant="ghost"
              onClick={() => resolveRemoteProfilePrompt({ action: 'cancel', profile: 'tailscale' })}
            >
              Cancel
            </Button>
          </div>
        </div>
      </div>
    )}
    ```
  - Notes: Uses two large clickable cards instead of a dropdown — this is a one-time choice and cards provide better UX for a binary decision with descriptions. Only a Cancel button in the footer since each card directly resolves the choice. LAN is listed first since it's the zero-config option (more likely for users hitting this dialog).

- [x] **Task 7: Add documentation to README.md**
  - File: `docs/README.md`
  - Action: Add a note about the profile chooser dialog in Section 3 "Remote Connection" (around line 241, after the profile table). Insert a brief paragraph:
    ```markdown
    > **First-time remote start:** When you click **Start Remote** for the first time,
    > a dialog asks you to choose between **LAN** and **Tailscale**. Pick **LAN** if both
    > machines are on the same local network — no extra setup is needed (a self-signed
    > certificate is generated automatically). Pick **Tailscale** if you need cross-network
    > access (requires Tailscale certificates — see Section 3.1 below).
    > You can change this later in **Settings → Client → Remote Profile**.
    ```
  - Notes: Keep it short and user-friendly. Place it right after the profile comparison table so users see it before diving into either option's setup steps.

- [x] **Task 8: Add documentation to README_DEV.md**
  - File: `docs/README_DEV.md`
  - Action: Add a subsection in the Remote/TLS area (near section 6.2 "Local vs Remote Mode" or section 6.4 "Tailscale HTTPS Setup") documenting the profile chooser flow:
    ```markdown
    #### Remote Profile Chooser Dialog

    When the user clicks "Start Remote" and `connection.remoteProfile` is still the
    default (`'tailscale'`) with no Tailscale cert files on disk, the app shows a
    modal asking them to choose LAN or Tailscale before proceeding.

    **Flow:**
    1. `startServerWithOnboarding()` (App.tsx) checks `mode === 'remote'`
    2. Calls `docker:checkTailscaleCertsExist` IPC → `checkTailscaleCertsExist()` in
       dockerManager.ts (reads config.yaml cert paths, expands tilde, checks `fs.existsSync`)
    3. If `connection.remoteProfile !== 'lan'` AND certs don't exist → shows modal
    4. User picks LAN or Tailscale → persists to `connection.remoteProfile` via `setConfig()`
    5. Container start resumes — `resolveTlsCertPaths()` now reads the chosen profile
       - LAN: auto-generates self-signed cert
       - Tailscale: validates cert files exist (shows error with instructions if missing)

    **Files involved:**
    - `dockerManager.ts` — `checkTailscaleCertsExist()` function
    - `main.ts` — `docker:checkTailscaleCertsExist` IPC handler
    - `preload.ts` — IPC bridge
    - `App.tsx` — modal state, request/resolve callbacks, JSX, check in startup flow
    ```
  - Notes: Technical audience. Focus on the flow and file locations so future developers can trace the logic.

### Acceptance Criteria

- [x] **AC 1 (Happy path — LAN):** Given the user has never started remote mode (profile is default `'tailscale'`, no Tailscale certs exist), when they click "Start Remote", then a modal appears asking them to choose LAN or Tailscale. When they click LAN, the modal closes, `connection.remoteProfile` is set to `'lan'`, and the container starts successfully with auto-generated self-signed certificates.

- [x] **AC 2 (Happy path — Tailscale with certs):** Given the user has Tailscale certificate files at the configured paths, when they click "Start Remote", then no modal appears and the container starts normally using the existing Tailscale certificates.

- [x] **AC 3 (Tailscale chosen, no certs):** Given the user has no Tailscale certs, when they click "Start Remote" and choose Tailscale in the modal, then the modal closes, `connection.remoteProfile` remains `'tailscale'`, and the existing `resolveTlsCertPaths()` error is shown with certificate generation instructions.

- [x] **AC 4 (Cancel):** Given the profile chooser modal is open, when the user clicks Cancel or the backdrop, then the modal closes and the server does not start.

- [x] **AC 5 (Subsequent starts):** Given the user previously chose LAN in the profile dialog, when they click "Start Remote" again, then no modal appears (the profile is already `'lan'`, skipping the check) and the container starts directly.

- [x] **AC 6 (Settings override):** Given the user changed the remote profile to LAN or Tailscale via Settings → Client → Remote Profile, when they click "Start Remote", then no modal appears regardless of cert file state (the profile is no longer the default).

- [x] **AC 7 (Documentation):** Given a user reads README.md Section 3, then they find a note explaining the first-time profile chooser dialog. Given a developer reads README_DEV.md, then they find a technical description of the profile chooser flow with file references.

## Additional Context

### Dependencies

- No new npm packages required
- Uses existing `Button` component (from `components/ui/`)
- Uses existing `getConfig`/`setConfig` from `src/config/store.ts`
- Uses existing IPC infrastructure (ipcMain, preload bridge)
- Uses existing helpers in dockerManager.ts (`readRemoteTlsProfile`, `extractYamlScalar`, `expandTilde`)

### Testing Strategy

**Manual testing (primary):**
1. **Fresh install test:** Delete `dashboard-config.json` (or the `connection.remoteProfile` key), ensure no Tailscale certs exist, click "Start Remote" → verify dialog appears
2. **LAN selection test:** Choose LAN in dialog → verify container starts, self-signed cert generated, `connection.remoteProfile` is `'lan'` in store
3. **Tailscale selection test:** Choose Tailscale in dialog (no certs) → verify existing error message appears
4. **Cancel test:** Click Cancel or backdrop → verify server does not start
5. **Subsequent start test:** After choosing LAN, click "Start Remote" again → verify dialog does NOT appear
6. **Tailscale certs present test:** Place cert files at configured paths, reset profile to `'tailscale'` → verify dialog does NOT appear, container starts normally
7. **Settings override test:** Change profile via Settings → Client → verify dialog does NOT appear on next remote start

**Unit testing (optional, low priority):**
- `checkTailscaleCertsExist()` in dockerManager.ts could be unit tested with mocked `fs.existsSync` and config.yaml content, but given the existing onboarding modals have no unit tests, this is not required for parity.

### Notes

- Related: GH Issue #43 (https://github.com/homelab-00/TranscriptionSuite/issues/43)
- The user reporting the bug is on Windows; the issue does not reproduce on Linux (where Tailscale paths may differ or the user has Tailscale installed)
- The `readRemoteTlsProfile()` function reads from the raw JSON file (`dashboard-config.json`) rather than via the electron-store API, because it runs in the main process outside of the store instance. The new IPC handler will follow the same pattern.
- Windows cert path: The default `host_cert_path` resolves to `C:\Users\<user>\.config\Tailscale\my-machine.crt` — this path doesn't exist by default on Windows (Tailscale on Windows stores certs elsewhere), which is why the bug manifests there.
- **Risk: AC 6 nuance** — The check condition is `currentProfile !== 'lan' && !certsExist`. If a user explicitly sets profile to `'tailscale'` in Settings (same as default), the dialog will still appear if certs are missing. This is actually correct behavior — the user hasn't provided certs yet, so prompting is appropriate. The dialog only skips when either (a) profile is `'lan'`, or (b) Tailscale certs exist.

## Review Notes

- Adversarial review completed 2026-03-23
- Findings: 12 total, 5 fixed, 7 skipped (noise/pre-existing/spec-acknowledged)
- Resolution approach: auto-fix

### Fixes Applied

- **F1**: Fixed `.catch()` called on potentially-undefined optional-chain result — replaced with safe ternary guard (`dockerApi?.checkTailscaleCertsExist ? await ... .catch(...) : false`)
- **F2**: Added comment in `checkTailscaleCertsExist` flagging the intentional config.yaml reading duplication with `resolveTlsCertPaths()` and directing future maintainers to keep both in sync
- **F3**: Added `console.warn` in the IPC error catch so failures surface in DevTools instead of silently resolving to `false`
- **F5**: Fixed README blockquote wording from "first time" (inaccurate) to "without Tailscale certificates configured" (accurate trigger condition)
- **F7**: Added `async` to `ipcMain.handle('docker:checkTailscaleCertsExist')` for consistency with all other IPC handlers in main.ts

### Findings Skipped

- **F4**: `checkTailscaleCertsExist` name — spec-defined, renaming would affect all layers; acceptable
- **F6**: Dialog shows for explicit Tailscale-in-Settings users without certs — spec-acknowledged correct behavior
- **F8**: `getConfig<'tailscale' | 'lan'>` cast — safe at runtime due to `!== 'lan'` guard
- **F9**: Missing accessibility attributes — pre-existing pattern across all onboarding modals; out of scope
- **F10**: `setConfig` error not surfaced — consistent with rest of `startServerWithOnboarding`
- **F11**: LAN cert could be missing on subsequent starts — pre-existing behavior, not introduced by this PR
- **F12**: YAML parser regex limitation — pre-existing constraint shared with `resolveTlsCertPaths()`
