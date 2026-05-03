---
title: 'Server View Image Selector & Runtime Icons Rework'
type: 'feature'
created: '2026-04-07'
status: 'done'
baseline_commit: '059ef09'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Docker image tag dropdown wastes space, makes it hard to see which version is selected, and the runtime profile buttons use generic icons that don't communicate which GPU vendor each mode targets.

**Approach:** Replace the dropdown with a row of selectable chip-boxes showing the 4 most recent stable releases (+ a "..." overflow popover for RC and older tags), and swap runtime profile icons for vendor logos (NVIDIA, AMD+Intel, Apple) with corrected labels and order.

## Boundaries & Constraints

**Always:**
- Date format DD/MM/YYYY everywhere (chips, popover items, image-available badge)
- RC tags in overflow popover only if their version > latest stable release
- "Older Releases" and "RC Releases" sections in overflow each show 4 initially + "Load All" button
- Most recent non-RC tag selected by default
- Fallback to local-only images when GHCR unreachable (no error toast)
- Brand SVG icons rendered inline as React components (no external image fetches)

**Ask First:** Adding new npm dependencies; changing the IPC return type shape if it would break other consumers

**Never:** Modify CustomSelect.tsx; add authentication requirements for GHCR date fetching; show RC tags in the main chip row

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Online, mixed tags | remoteTags = [v1.3.0, v1.2.2, v1.2.1, v1.1.4, v1.1.3, v1.1.2, ...] | 4 chips: v1.3.0 (selected), v1.2.2, v1.2.1, v1.1.4 + "..." chip | N/A |
| RC newer than latest | remoteTags includes v1.3.1rc | RC section in overflow shows v1.3.1rc | N/A |
| RC older than latest | remoteTags includes v1.2.9rc | RC section omits v1.2.9rc | N/A |
| Offline | remoteTags = [] | Show local tags as chips, no overflow | Silent fallback |
| No local images | images = [], remoteTags available | Chips show remote tags, none has checkmark | Pull to download |
| Date fetch partial failure | Some manifest fetches fail | Chips without dates show tag only (no date line) | Graceful omission |

</frozen-after-approval>

## Code Map

- `dashboard/electron/dockerManager.ts` -- Enhance `listRemoteTags()` to return `{tag, created}[]` via OCI manifest config blobs
- `dashboard/electron/main.ts` -- IPC handler shape update (if needed)
- `dashboard/electron/preload.ts` -- IPC bridge type update
- `dashboard/src/types/electron.d.ts` -- Type declaration update
- `dashboard/src/hooks/useDocker.ts` -- Update `remoteTags` type from `string[]` to `RemoteTag[]`
- `dashboard/src/services/versionUtils.ts` -- Add `formatDateDMY()` helper, add `isNewerThan()` for RC filtering
- `dashboard/components/views/ServerView.tsx` -- Replace image selector UI + runtime profile changes
- `dashboard/components/ui/ImageTagChips.tsx` -- New component: chip row + overflow popover
- `dashboard/components/ui/icons/` -- New directory: NvidiaIcon, AmdIcon, IntelIcon, AppleIcon SVG components

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/services/versionUtils.ts` -- Add `formatDateDMY(isoOrDateStr)` returning `DD/MM/YYYY`; add `isNewerVersion(a, b)` returning true if tag `a` has higher semver than `b`
- [x] `dashboard/src/services/versionUtils.test.ts` -- Unit tests for new utils
- [x] `dashboard/electron/dockerManager.ts` -- Change `listRemoteTags()` to return `{tag: string, created: string | null}[]`; after fetching tags, fetch manifest+config for each in parallel to extract `created` timestamp; use `Promise.allSettled` so partial failures don't block
- [x] `dashboard/electron/preload.ts` + `dashboard/src/types/electron.d.ts` -- Update `listRemoteTags` return type to `Array<{tag: string, created: string | null}>`
- [x] `dashboard/src/hooks/useDocker.ts` -- Change `remoteTags` from `string[]` to `Array<{tag: string, created: string | null}>`; update `UseDockerReturn`
- [x] `dashboard/components/ui/icons/NvidiaIcon.tsx` + `AmdIcon.tsx` + `IntelIcon.tsx` + `AppleIcon.tsx` -- Brand logo SVG components (white fill, accept `size` and `className` props)
- [x] `dashboard/components/ui/ImageTagChips.tsx` -- New component: horizontal chip row (4 stable tags + "..." overflow); overflow popover with "RC Releases" and "Older Releases" sections; each item shows tag + optional date (DD/MM/YYYY); selected chip highlighted; "Load All" buttons in each section
- [x] `dashboard/components/views/ServerView.tsx` -- Replace CustomSelect image selector with `ImageTagChips`; remove "Scan Local Images" button; reorder runtime buttons to CUDA → Vulkan → Metal → CPU; rename Vulkan to "GPU (Vulkan)"; swap icons to NvidiaIcon, AmdIcon+IntelIcon, AppleIcon; change date format in image-available badge to DD/MM/YYYY
- [x] `dashboard/components/__tests__/ServerView.test.tsx` -- Mock compatible with new `remoteTags: RemoteTag[]` shape (empty array works for both)

**Acceptance Criteria:**
- Given remote tags are available, when the image section renders, then 4 chip-boxes show the 4 most recent stable tags with the newest selected by default
- Given a "..." chip is clicked, when a popover opens, then it shows "RC Releases" (only versions > latest stable) and "Older Releases" (4 initially, expandable via Load All)
- Given any date is displayed, when rendered, then it uses DD/MM/YYYY format
- Given the runtime section renders, then buttons appear in order CUDA, Vulkan, Metal, CPU with vendor logo icons and "GPU (Vulkan)" label

## Design Notes

**Chip layout:** Horizontal flex row with equal-width boxes. Selected chip has accent border + glow (matching existing accent-cyan style). Unselected chips use `border-white/10 bg-white/5`. The "..." chip is visually distinct (same size, centered ellipsis).

**Overflow popover:** Uses Headless UI `Popover` (already a project dependency). Anchored below the "..." chip. Two sections with `text-xs text-slate-500` headers. Each item is a clickable row: `tag | date`. "Load All" is a text button at section bottom.

**Date fetching:** `listRemoteTags()` fetches OCI manifest per tag (parallel via `Promise.allSettled`), extracts config digest, fetches config blob for `created` field. One shared anonymous bearer token. Tags without dates gracefully show tag-only (no date line). Total timeout 10s for the full operation.

**Brand icons:** Minimal SVG paths from canonical brand assets. ~20-30 lines each. White fill inheriting text color. AMD+Intel rendered side-by-side in a single button with a small gap.

## Verification

**Commands:**
- `cd dashboard && npx vitest run` -- expected: all tests pass
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors

**Manual checks:**
- Image section shows 4 chips + "..." overflow with correct date format
- Runtime buttons show in correct order with vendor logos
- Offline: chips fall back to local images only

## Suggested Review Order

**Image Tag Chip Selector**

- New component: chip row + overflow popover replacing the CustomSelect dropdown
  [`ImageTagChips.tsx:27`](../../dashboard/components/ui/ImageTagChips.tsx#L27)

- Merged tag list builder using RemoteTag[] shape; fallback to local-only when offline
  [`ServerView.tsx:939`](../../dashboard/components/views/ServerView.tsx#L939)

- OCI manifest + config blob date fetching with separate 8s timeout for parallel phase
  [`dockerManager.ts:2534`](../../dashboard/electron/dockerManager.ts#L2534)

- Per-tag date fetch — manifest → config digest → created timestamp
  [`dockerManager.ts:2494`](../../dashboard/electron/dockerManager.ts#L2494)

**Version Utilities**

- RC version comparison for overflow filter; UTC-safe DD/MM/YYYY formatter
  [`versionUtils.ts:66`](../../dashboard/src/services/versionUtils.ts#L66)

- Unit tests: isNewerVersion + formatDateDMY (12 new tests)
  [`versionUtils.test.ts:97`](../../dashboard/src/services/versionUtils.test.ts#L97)

**Runtime Profile Icons**

- Reordered buttons: CUDA → Vulkan → Metal → CPU with brand SVG icons
  [`ServerView.tsx:1649`](../../dashboard/components/views/ServerView.tsx#L1649)

- NVIDIA logo SVG component (representative of all 4 brand icons)
  [`NvidiaIcon.tsx:10`](../../dashboard/components/ui/icons/NvidiaIcon.tsx#L10)

**IPC Type Changes**

- RemoteTag interface + updated return type in hook, preload, and type declaration
  [`useDocker.ts:15`](../../dashboard/src/hooks/useDocker.ts#L15)
