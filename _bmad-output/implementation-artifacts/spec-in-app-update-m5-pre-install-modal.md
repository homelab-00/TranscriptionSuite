---
title: 'M5: Pre-install modal for in-app Dashboard updates'
type: 'feature'
created: '2026-04-13'
status: 'done'
baseline_commit: '1dc2779d97441916491139f1cf2bb8cd8f32d02f'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-12-in-app-updates.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m2-banner-ui.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-in-app-update-m4-compat-guard.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `UpdateBanner`'s `[Download]` button calls `updates.download()` immediately — no release-notes preview, no visible compat verdict, no recovery path when M4 rejects with `incompatible-server`. `UpdateManager.checkApp()` already fetches the GitHub release `body` but discards it. The brainstorming locks in one consolidated pre-install surface: *what's changing* + *compat verdict* + *one recovery path* (pull newer server image), then commit.

**Approach:** New `<UpdateModal>` opens on `[Download]` click instead of the banner calling `api.download()` directly. Modal calls `updates.checkCompatibility()` for a live verdict, renders persisted release notes via the existing `react-markdown` + `remark-gfm` pattern from `AudioNoteModal.tsx`, and shows three footer buttons: **[Install Dashboard]** (fires `api.download()` via parent callback, then closes), **[Update Server First]** (only when `incompatible` + `deployment:'local'` — pulls latest server image via the existing `docker.pullImage` IPC), **[Cancel]**. Release notes piggyback on `UpdateManager` by widening `ComponentUpdateStatus` with `releaseNotes: string | null`. No new IPC channels.

## Boundaries & Constraints

**Always:**
- New file `dashboard/components/ui/UpdateModal.tsx` exports `UpdateModal` + `UpdateModalProps`. Props: `{ isOpen, targetVersion: string|null, currentVersion: string, onClose: () => void, onConfirmInstall: () => void }`. Modal NEVER calls `updates.download()` itself — confirmation bubbles through `onConfirmInstall`.
- Lifecycle mirrors `BugReportModal.tsx` (lines 36–79): `isRendered` + `isVisible` double-RAF entry, 500ms exit timer, `fixed inset-0 z-50` overlay, `bg-black/40 backdrop-blur-sm`, rounded-3xl glass card. Close via backdrop click AND `[Cancel]`.
- On each `isOpen` flip to true: fetch `updates.checkCompatibility()` and `updates.getStatus()`. Never cache across opens.
- Release notes render from `updateStatus.app.releaseNotes`. If null/empty → literal `"No release notes published for this version."` (no markdown pipeline).
- Markdown: `ReactMarkdown` + `remarkGfm` with a LOCAL `RELEASE_NOTES_MARKDOWN_COMPONENTS` map inside this file (do not import from `AudioNoteModal`). Scroll container `max-h-80 overflow-y-auto`. Anchor clicks route through `window.electronAPI.app.openExternal` via the `preventDefault` pattern in `BugReportModal.tsx:22–34`. No `rehypeRaw`, no raw HTML.
- Button rules:
  - `[Install Dashboard]` always visible. Disabled iff `compat.result === 'incompatible'`. Click → `onConfirmInstall()` → modal closes.
  - `[Update Server First]` visible iff `compat.result === 'incompatible' && compat.deployment === 'local'`. Click → `docker.pullImage(updateStatus.server.latest)` with button-local spinner. On success: `sonner` toast `"Server image updated. Restart the server from the Server tab to apply, then re-run the update."`, re-fetch compat, modal stays open. On failure: toast the error, modal stays open.
  - `[Cancel]` always visible → `onClose()`.
- Verdict badge above the buttons:
  - `compatible` → green, `"Compatible with your server (v{serverVersion})"`.
  - `incompatible` → amber, `"Your server (v{serverVersion}) needs v{compatibleRange} — update server first."` (swap tail to `"…update your remote server manually."` when `deployment==='remote'`).
  - `unknown` → slate, `"Could not verify server compatibility ({reason}). Install anyway?"` — [Install Dashboard] stays enabled (fail-open per M4).
  - pending → `"Checking server compatibility…"` + spinner; both confirm buttons disabled.
- `UpdateBanner.tsx`: add `isModalOpen` state + `appVersion` state (from `app.getVersion()` in existing mount effect). Replace `handleDownload` body with `setIsModalOpen(true)`. New `handleConfirmInstall` wraps the old `api.download()` call (keep existing try/catch + `console.error`). Render `<UpdateModal>` once at JSX root. Modal mounts only when derived state is `available` or `ready`; `downloading` + `ready_blocked` unaffected.
- `updateManager.ts`: widen `ComponentUpdateStatus` with `releaseNotes: string | null`. In `checkApp()` capture `data.body` (trim, 50 000-char cap, null when empty). Set `releaseNotes: null` on every error/fallback path AND in `checkServer()` for type consistency. Read sites use `?? null` for pre-M5 persisted statuses.
- Mirror `releaseNotes` field in `dashboard/src/types/electron.d.ts::ComponentUpdateStatus` and `dashboard/electron/preload.ts` if it re-declares the type.
- Tests: new `UpdateModal.test.tsx` covering the I/O matrix; update `UpdateBanner.test.tsx` Download-click case + add `handleConfirmInstall` case. Match existing mock idiom (stub `globalThis.window.electronAPI`).

**Ask First:**
- Auto-restarting the server after `pullImage` success (v1 leaves it to the user).
- Streaming `pullImage` progress (v1 is spinner + toast only).
- Any change to `manifest.json` shape or `CompatResult` (frozen by M4).

**Never:**
- Do NOT call `updates.install()` from the modal (that's M3's install-gate after download completes).
- Do NOT call `autoUpdater`/`UpdateInstaller` from the renderer. Only `window.electronAPI.updates.*`.
- Do NOT restart the Docker container, call `stopContainer`, or touch `gracefulShutdown`.
- Do NOT add `updates:fetchReleaseNotes` IPC — reuse `getStatus()`.
- Do NOT enable `rehypeRaw` or render raw HTML. Do NOT let renderer anchors navigate.
- Do NOT block on a failed compat fetch — degrade to `unknown` + fail-open.
- Do NOT regress any `UpdateBanner.test.tsx` case — only update tests whose expectation changed, with a one-line why.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Behavior |
|---|---|---|
| Compatible happy path | compat=`{result:'compatible', serverVersion:'1.4.2'}`, notes present | Green badge, markdown renders, [Install Dashboard] enabled → `onConfirmInstall()` fires, modal closes. |
| Incompatible + local | `{result:'incompatible', deployment:'local', serverVersion:'1.0.0', compatibleRange:'>=1.5.0'}` | Amber badge. [Install Dashboard] disabled. [Update Server First] visible. |
| Incompatible + remote | same with `deployment:'remote'` | Amber badge (remote copy). [Install Dashboard] disabled. [Update Server First] HIDDEN. |
| Unknown compat | `{result:'unknown', reason:'server-version-unavailable'}` | Slate badge. [Install Dashboard] ENABLED (fail-open). [Update Server First] hidden. |
| Release notes absent | `app.releaseNotes === null` | Literal fallback text. `ReactMarkdown` NOT invoked. |
| Release notes oversized | body >50 000 chars | Trimmed at capture time in `checkApp()`. |
| Update Server First success | click → `pullImage('1.5.0')` resolves | Toast with restart instruction. Re-fetch compat. Modal stays open. |
| Update Server First failure | pullImage rejects | Toast with error. Button returns to idle. Modal stays open. |
| Compat fetch pending | first render after open | Spinner + "Checking…"; both confirm buttons disabled. |
| Compat fetch throws | IPC rejects | Treat as `unknown` / `manifest-fetch-failed`. Fail-open. |
| Open → close → reopen | isOpen toggles | Both compat and release notes re-fetched on each open. |
| External link click | markdown contains `[x](https://…)` | `app.openExternal(url)` called; renderer does NOT navigate. |

</frozen-after-approval>

## Code Map

- `dashboard/components/ui/UpdateModal.tsx` — NEW. Modal, markdown components map, badge-copy helpers.
- `dashboard/components/ui/UpdateBanner.tsx` — open modal on `[Download]`, keep `api.download()` in new `handleConfirmInstall`, add `appVersion` state.
- `dashboard/electron/updateManager.ts` — widen `ComponentUpdateStatus` with `releaseNotes: string | null`; capture `data.body` in `checkApp()`.
- `dashboard/src/types/electron.d.ts` — mirror `releaseNotes`.
- `dashboard/electron/preload.ts` — mirror if it re-declares `ComponentUpdateStatus`.
- `dashboard/components/ui/__tests__/UpdateModal.test.tsx` — NEW. All I/O matrix rows + lifecycle + link rewiring + toast assertions.
- `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — update Download-click test; add `handleConfirmInstall` case.

Not changed: `compatGuard.ts`, `updateInstaller.ts`, `installGate.ts`, `main.ts`, `appState.ts`, `dockerManager.ts`.

## Spec Change Log

- **2026-04-13 — post-draft hardening (patches applied in-review):**
  - `react-markdown` v10 removed the `inline` prop on the `code` component — the original map's `inline ? ... : ...` ternary was a dead branch that would render inline `` `code` `` as full-block. Replaced with a bare inline `code` renderer and a `pre` override for fenced blocks.
  - Release-note anchors now gate `app.openExternal` through an `isSafeExternalUrl()` allow-list (`http:`/`https:`/`mailto:` only). Prevents a `javascript:`/`file:`/`data:` URL in an attacker-influenceable release body from reaching the OS shell.
  - `isModalOpen` reset effect added to `UpdateBanner`: flipping away from `available` clears the flag so a round-trip `available → downloading → available` no longer silently reopens the modal.
  - `handleUpdateServerFirst` now guards every async continuation against unmount via a `mountedRef`. Cancel button + backdrop click are suppressed during `pullInProgress` so users cannot orphan a Docker pull.
  - `sanitizeReleaseBody()` now truncates on code-point boundaries (`Array.from` split) to avoid lone UTF-16 surrogates at the 50 000-char cap — emoji-heavy release bodies no longer render replacement characters.
  - `UpdateModal` `aria-label` is now `"Dashboard update — release notes and install confirmation"` (previously collided with `UpdateBanner`'s identical `"Update available"` live-region label, which screen readers would conflate).
  - `installDisabled` now includes `compat === null` (a non-Electron renderer where `checkCompatibility` was never invoked would otherwise enable the button).
  - Double-click / Enter-spam on `[Install Dashboard]` is latched via `confirmedRef` so `onConfirmInstall` fires at most once per open.
  - `window.electronAPI?.app?.getVersion().then(…)` pattern replaced with an extracted `getVersionFn` function-typeof check — the original expression called `.then()` on the optional-chain result, which would throw `TypeError` when `app` is undefined (e.g., non-Electron dev mode).
  - Two new test cases cover the post-patch surface: protocol-allow-list blocks `javascript:`/`file:` URLs; double-click Install fires once. Seven new tests in `electron/__tests__/updateManager.test.ts` cover `sanitizeReleaseBody`'s whitespace / under-cap / exactly-at-cap / over-cap / surrogate-split rows.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/updateManager.ts` — added `releaseNotes: string | null` to `ComponentUpdateStatus`; captured `data.body` via `sanitizeReleaseBody()` (trim + 50 000-char cap + null-for-empty) in `checkApp()`; set `releaseNotes: null` on every error/fallback + in `checkServer()`.
- [x] `dashboard/src/types/electron.d.ts` — mirrored the field on the ambient type.
- [x] `dashboard/electron/preload.ts` — mirrored the field on the re-declared interface at line 357.
- [x] `dashboard/components/ui/UpdateModal.tsx` — NEW. Full lifecycle (double-RAF + 500ms exit), local `RELEASE_NOTES_MARKDOWN_COMPONENTS` map (external anchors route through `app.openExternal`), pure `deriveBadgeContent()` helper, three-button footer with correct disable/visibility rules per I/O matrix.
- [x] `dashboard/components/ui/UpdateBanner.tsx` — added `isModalOpen` + `appVersion` state; `handleDownload` now opens the modal; new `handleConfirmInstall` wraps `api.download()`; `<UpdateModal>` rendered in a fragment only when `derived.state === 'available'`.
- [x] `dashboard/components/ui/__tests__/UpdateModal.test.tsx` — NEW. 20 Vitest cases covering: pure badge mapper (5), closed-on-first-mount (1), compatible happy path (1), incompatible local + remote (2), unknown fail-open (1), release-notes null fallback (1), Update-Server-First success / failure / missing tag (3), compat pending + compat throws (2), open→close→reopen refetch (1), Cancel + backdrop close (2), external-link rewiring with `preventDefault` (1).
- [x] `dashboard/components/ui/__tests__/UpdateBanner.test.tsx` — added `checkCompatibility` + `getVersion` + `docker.pullImage` to the harness, widened `installHarness`, updated the Download-click test to assert the modal opens AND `api.download()` is NOT called, added a new case asserting `[Install Dashboard]` in the modal fires `api.download()`.

**Acceptance Criteria:**
- Given compat=`compatible` + notes present, when user clicks `[Download]` then `[Install Dashboard]`, then `updates.download()` is called exactly once AND the modal closes.
- Given compat=`incompatible` + local + `server.latest='1.5.0'`, when `[Update Server First]` is clicked, then `docker.pullImage('1.5.0')` is called once, modal stays open, and a toast containing `"Restart the server"` appears.
- Given compat=`incompatible` + remote, then `[Update Server First]` is NOT rendered AND `[Install Dashboard]` is disabled.
- Given compat=`unknown`, then `[Install Dashboard]` is enabled AND slate badge text contains `"Could not verify"`.
- Given `app.releaseNotes === null`, then fallback text renders AND `ReactMarkdown` is not invoked (assert via absence of a known markdown DOM marker).
- Given an external-URL anchor click, `app.openExternal(url)` is called AND default navigation is prevented.
- `cd dashboard && npm run typecheck && npm run test && npm run build:electron` — all green. Existing `UpdateBanner` tests continue to pass (edits only where interception semantics changed, with inline comment).

## Design Notes

**Why reuse `updateStatus.app.releaseNotes` (no new IPC):** The body is already on the wire — `checkApp()` fetches the full GitHub release payload and throws everything but `tag_name` away. Capturing one more field is additive and safe. A dedicated IPC would duplicate network cost for ≤24 h freshness gain; release bodies rarely change post-publish.

**Why `[Install Dashboard]` delegates up to the banner:** The banner already owns the `api.download()` error-recovery pattern. Re-use preserves single-source logging and keeps the modal purely a UI router.

**Why `[Update Server First]` only pulls (no restart):** A restart mid-transcription is a data-loss risk; M3 already guards `gracefulShutdown`. Adding a second restart entrypoint would need the same idle wiring. v1 ships pull + human handoff to the Server tab — honest about what the button actually achieves.

**Why 50 000-char release-notes cap:** GitHub caps bodies at ~125 000 but a pathological payload still stresses the markdown renderer. 50 000 ≈ 20 screens of prose — plenty for any realistic changelog.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — zero errors.
- `cd dashboard && npm run test -- UpdateModal UpdateBanner` — all new + existing cases pass.
- `cd dashboard && npm run build:electron` — compiles.

**Manual gate (optional, Linux AppImage):** Publish a test release with `manifest.json` declaring `compatibleServerRange: '>=99.0.0'`. Start dashboard, click `[Download]`. **Expect:** modal with notes, amber badge, [Install Dashboard] disabled, [Update Server First] visible. Click [Update Server First] → spinner → restart toast. [Cancel] → banner back to `available`. Restore manifest → reopen → green badge → [Install Dashboard] proceeds.
