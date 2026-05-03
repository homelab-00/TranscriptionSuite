---
title: 'Consolidate RuntimeProfile type definitions (DRY)'
type: 'refactor'
created: '2026-04-04'
status: 'done'
baseline_commit: '0ea117e'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `RuntimeProfile` is independently defined in 7 files across the dashboard. Two definitions (`electron.d.ts:18` and `useDocker.ts:112`) are stale — they define `'gpu' | 'cpu' | 'vulkan'` and are **missing `'metal'`**, silently causing type errors on Metal paths. Future profile additions (e.g. a new backend) will repeat this miss.

**Approach:** Define `RuntimeProfile` once in a new shared types module (`src/types/runtime.ts`), export it, and replace all 7 local definitions with imports. Update `electron.d.ts` to reference the canonical type so the renderer-side `ElectronAPI` stays correct.

## Boundaries & Constraints

**Always:**
- The canonical type must include all four values: `'gpu' | 'cpu' | 'vulkan' | 'metal'`
- All files that previously defined RuntimeProfile locally must import from the canonical source
- TypeScript compilation (`npx tsc --noEmit`) must pass after the refactor
- No runtime behavior changes — this is a types-only refactor

**Ask First:**
- If any file's build pipeline cannot resolve the import from `src/types/runtime.ts` (e.g. Electron main process tsconfig), ask before choosing an alternative path

**Never:**
- Do not change any runtime logic, component behavior, or UI rendering
- Do not rename the type or change its values beyond fixing the missing `'metal'`
- Do not refactor `StartContainerOptions` or other interfaces in this spec

</frozen-after-approval>

## Code Map

- `dashboard/src/types/runtime.ts` -- NEW: canonical RuntimeProfile definition
- `dashboard/src/types/electron.d.ts:18` -- STALE: missing 'metal', replace with import/reference
- `dashboard/electron/preload.ts:32` -- has correct type, replace with import
- `dashboard/src/hooks/useDocker.ts:112` -- STALE: missing 'metal', replace with import
- `dashboard/App.tsx:50` -- local definition, replace with import
- `dashboard/components/views/ServerView.tsx:61` -- local definition, replace with import
- `dashboard/components/views/SessionView.tsx:63,101` -- inline union, replace with import
- `dashboard/components/views/SettingsModal.tsx:129,263` -- inline casts, replace with import
- `dashboard/components/Sidebar.tsx:35` -- inline union in interface, replace with import

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/types/runtime.ts` -- Create file exporting `RuntimeProfile = 'gpu' | 'cpu' | 'vulkan' | 'metal'`
- [x] `dashboard/src/types/electron.d.ts` -- Fix missing 'metal', add sync comment
- [x] `dashboard/electron/preload.ts` -- Add sync comment (already correct, isolated build)
- [x] `dashboard/electron/dockerManager.ts` -- Add sync comment (already correct, isolated build)
- [x] `dashboard/src/hooks/useDocker.ts` -- Remove local RuntimeProfile, import from canonical source
- [x] `dashboard/App.tsx` -- Remove local RuntimeProfile, import from canonical source
- [x] `dashboard/components/views/ServerView.tsx` -- Remove local RuntimeProfile, import from canonical source
- [x] `dashboard/components/views/SessionView.tsx` -- Replace inline unions with imported RuntimeProfile
- [x] `dashboard/components/views/SettingsModal.tsx` -- Replace inline casts with imported RuntimeProfile
- [x] `dashboard/components/Sidebar.tsx` -- Replace inline union with imported RuntimeProfile

**Acceptance Criteria:**
- Given a clean checkout, when `cd dashboard && npx tsc --noEmit` runs, then zero type errors related to RuntimeProfile
- Given any file that previously defined RuntimeProfile, when searched with grep, then no local `type RuntimeProfile` or inline `'gpu' | 'cpu' | 'vulkan'` unions remain (all replaced with imports)
- Given `electron.d.ts` and `useDocker.ts`, when inspected, then `'metal'` is now included via the canonical import

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `grep -rn "type RuntimeProfile" dashboard/ --include="*.ts" --include="*.tsx"` -- expected: only `src/types/runtime.ts` defines it
- `grep -rn "'gpu' | 'cpu' | 'vulkan'" dashboard/ --include="*.ts" --include="*.tsx"` -- expected: all remaining matches include 'metal' and carry sync comments

## Suggested Review Order

- Canonical type definition — single source of truth for the union
  [`runtime.ts:8`](../../dashboard/src/types/runtime.ts#L8)

- Bug fix: ambient declaration was missing 'metal', now corrected with sync comment
  [`electron.d.ts:18`](../../dashboard/src/types/electron.d.ts#L18)

- Bug fix: stale 3-value union replaced with canonical import (moved to top-level imports)
  [`useDocker.ts:11`](../../dashboard/src/hooks/useDocker.ts#L11)

- Local definition replaced with import; interface and useState now use RuntimeProfile
  [`SessionView.tsx:57`](../../dashboard/components/views/SessionView.tsx#L57)

- Local definition replaced with import
  [`ServerView.tsx:60`](../../dashboard/components/views/ServerView.tsx#L60)

- Local definition replaced with import
  [`App.tsx:48`](../../dashboard/App.tsx#L48)

- Inline casts replaced with RuntimeProfile type reference
  [`SettingsModal.tsx:42`](../../dashboard/components/views/SettingsModal.tsx#L42)

- Inline union in props interface replaced with import
  [`Sidebar.tsx:19`](../../dashboard/components/Sidebar.tsx#L19)

- Sync comments added (isolated Electron build — cannot import from src/)
  [`preload.ts:32`](../../dashboard/electron/preload.ts#L32)
  [`dockerManager.ts:113`](../../dashboard/electron/dockerManager.ts#L113)
