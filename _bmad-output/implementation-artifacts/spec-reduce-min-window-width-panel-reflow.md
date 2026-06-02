---
title: 'Reduce Minimum Window Width via Panel Reflow'
type: 'feature'
created: '2026-06-01'
status: 'done'
baseline_commit: '410878002c6c0402a73fd90241b6ef8a959522f3'
context: ['{project-root}/.claude/skills/ui-contract/SKILL.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Electron window cannot be narrowed below `minWidth: 1262` because the Session tab's two-column layout forces a floor of `sidebar + left-panel-min + right-panel-min`. Users on small or split screens cannot make the window narrower.

**Approach:** Lower the OS `minWidth` to `sidebar + left-panel-min`, and make the *already-existing-but-unreachable* single-column reflow actually work. Below a content-width threshold: the Session right panel (Audio Visualizer + Live Mode) stacks **below** the left panel as one scrolling column, and the Notebook Morning/Afternoon block stacks **below** the calendar. Trigger via Tailwind v4 container queries (so a collapsed sidebar frees real space), with the reflow animated using existing timings.

## Boundaries & Constraints

**Always:**
- New `minWidth` = expanded sidebar (192px) + left-panel min-usable + view horizontal padding; keep `minHeight: 600`.
- Reflow trigger is based on the **content-area width** (window − live sidebar width) via a Tailwind v4 `@container` on the content wrapper — NOT viewport media queries. Collapsing the sidebar must free width for the layout.
- In stacked mode the content scrolls as a single outer column — nothing clipped or unreachable. The two-column independent-scroll + baseline-height machinery must not misbehave when stacked.
- Reuse existing animation primitives: the `slideInLeft`/`slideInRight` keyframes (`NotebookView.tsx:1170`, `0.3s cubic-bezier(0.16,1,0.3,1)`) and existing `transition` durations (300/500). Respect `prefers-reduced-motion`.
- Sidebar keeps its fixed width and collapse behavior — it is not part of the reflow.
- Wide-window layout (≥ threshold) is visually identical to today.

**Ask First:**
- If the left panel / calendar is not usable at ~480px and the computed `minWidth` must rise materially above ~760px, confirm the final value with the user.

**Never:**
- Do NOT use `animate-in` / `fade-in` / `slide-in-from-*` utilities — no `tailwindcss-animate` plugin is installed, so they are dead no-ops.
- Do NOT add animation libraries or Tailwind plugins.
- Do NOT change sidebar widths/collapse, Vite `base`, or the layout of Server/Models/Logs/Settings views.
- No backend changes.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Wide window | content width ≥ threshold | Session: left/right side-by-side; Notebook: calendar + Morning/Afternoon side-by-side (as today) | N/A |
| Narrow window | content width < threshold | Session: right panel stacked below left as one scrolling column; Notebook: Morning/Afternoon below calendar | N/A |
| Sidebar collapsed near threshold | collapse frees ~112px | layout uses freed width — can stay/return to side-by-side at a narrower window than when expanded | N/A |
| At new `minWidth` | window at minimum | left panel / calendar fully usable; stacked; content scrolls; nothing clipped | N/A |
| Resize crosses threshold | width crosses boundary | reflowed block plays entrance animation (reused `slideIn` timing) | N/A |
| Reduced motion | `prefers-reduced-motion: reduce` | reflow occurs instantly, no animation | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/electron/main.ts:765-781` -- `BrowserWindow` `minWidth: 1262` → lower; keep `minHeight: 600`. No other `setMinimumSize`.
- `dashboard/App.tsx:781` -- view content wrapper (`relative h-full flex-1 overflow-hidden`); add Tailwind `@container` here so descendant grids can query content-area width.
- `dashboard/components/views/SessionView.tsx:1288` -- main grid (`lg:grid-cols-[minmax(480px,5fr)_minmax(300px,7fr)]`); columns at `:1290`/`:1938` (`overflow-hidden`, fixed-height); inner scroll containers `:1317`/`:1965`; baseline-height/scroll-indicator effects `:1067-1108` (must no-op when stacked).
- `dashboard/components/views/NotebookView.tsx:1168` -- CalendarTab grid (`lg:grid-cols-3`); calendar col `:1175` (`lg:col-span-2`); timeslots col `:1280` (`overflow-hidden h-full`); reusable `slideIn` keyframes `:1170-1173`.
- `dashboard/src/index.css:258-264` -- `prefers-reduced-motion: reduce` block (extend if a new named keyframe is added).
- `dashboard/components/Sidebar.tsx:54-55` -- reference only: fixed widths 80 (collapsed) / 192 (expanded). No change.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/electron/main.ts` -- lower `minWidth` 1262 → computed value (expanded sidebar 192 + left grid min 480 + view padding ~48 ≈ **720**); keep `minHeight: 600`. Verify the left panel is usable at that width.
- [x] `dashboard/App.tsx` -- add Tailwind v4 `@container` (container-type: inline-size) to the line 781 content wrapper so child grids query content-area width.
- [x] `dashboard/components/views/SessionView.tsx` -- replace viewport `lg:` grid (line 1288) with a container-query variant at the Session threshold (~840px): base `grid-cols-1`, `@min-[840px]:grid-cols-[minmax(480px,5fr)_minmax(300px,7fr)]`. In stacked (`@max-[839px]:`) mode, make the grid scroll as one outer column and neutralize per-column `overflow-hidden`/fixed-height so nothing clips; ensure scroll-indicator + baseline-height effects no-op when stacked. Animate the right column's entrance-below with the reused `slideIn` timing.
- [x] `dashboard/components/views/NotebookView.tsx` -- replace viewport `lg:grid-cols-3` / `lg:col-span-2` (lines 1168/1175) with container-query variants at the Notebook threshold (~860px): base single column (Morning/Afternoon below calendar), side-by-side above threshold; calendar `h-full` → auto-height when stacked so CalendarTab scrolls as one column. Reuse the `slideInLeft`/`slideInRight` keyframes for the timeslots entrance.
- [x] `dashboard/src/index.css` -- if a new named reflow keyframe is added, register it in the `@media (prefers-reduced-motion: reduce)` block (line 258) so the reflow is instant; if only existing keyframes/utilities are reused, confirm reduced-motion still suppresses them.
- [x] UI contract -- after CSS-class edits, run the pipeline (`extract` → `build` → `validate --update-baseline` → `check`) and bump `meta.spec_version` (per `ui-contract` skill).

**Acceptance Criteria:**
- Given the app at default size, when the user drags the window narrower past the old ~1262 limit, then it keeps shrinking down to ~720px (no longer hard-stopped).
- Given a window too narrow to fit both Session panels, when rendered, then the right panel (Audio Visualizer + Live Mode) is stacked below the left panel as one scrolling column with all content reachable (no clipping, no dead scroll region).
- Given a narrow window on Notebook, when rendered, then Morning and Afternoon appear below the calendar and the page scrolls to reach them.
- Given a window near the threshold, when the user collapses the sidebar, then the freed width is used (layout can stay/return to side-by-side at a narrower window than with the sidebar expanded) — proving container-based (not viewport) reflow.
- Given the layout crosses the threshold during resize with motion allowed, then the reflowed block animates in via an existing timing (~300ms `cubic-bezier(0.16,1,0.3,1)`); given reduced motion, then the reflow is instant.
- Given a wide window, when rendered, then Session and Notebook are visually identical to today (no regression).

## Design Notes

- **Why container queries:** the reflow must respond to the content area's actual width (window − live sidebar), so collapsing the sidebar buys back horizontal space. A viewport `lg:` media query cannot see the sidebar state. Tailwind v4 has native `@container` / `@min-[…]:` — add `@container` once on the content wrapper; other views' existing viewport breakpoints are unaffected.
- **Animation reuse, not invention:** `slideInLeft`/`slideInRight` (`NotebookView.tsx:1170`) are the project's existing reflow-entrance keyframes. The `animate-in`/`slide-in-from-*` strings in `App.tsx:802` are dead (no plugin) — do not copy them.
- **Stacked-mode scrolling is the main risk:** the two-column design fills a fixed viewport height with independent inner scroll per column. Stacked, that clips silently. Switch stacked mode to a single outer scroll with natural row heights.
- **`minWidth` math:** 192 (expanded sidebar) + 480 (left grid min) + ~36–48 (`SessionView` `pl-6`+`pr-3` / `NotebookView` `p-6`) ≈ 708–720. Notebook single-column (calendar min ~480 + padding + sidebar) is consistent, so one `minWidth` ≈ 720 covers both.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: no TypeScript errors.
- `cd dashboard && npm run ui:contract:check` -- expected: contract passes after baseline update + `spec_version` bump.

**Manual checks:**
- Launch app; drag window narrow → confirm it shrinks to ~720px, Session right panel stacks below left and scrolls, nothing clipped.
- Switch to Notebook at narrow width → Morning/Afternoon are below the calendar and reachable by scroll.
- Collapse sidebar near the threshold → confirm freed width is used (side-by-side persists at a narrower window).
- Enable OS reduced-motion → confirm reflow is instant; disable → confirm entrance animation plays.
- Widen window → confirm Session/Notebook match the current look exactly.

## Suggested Review Order

**Container-query foundation (start here)**

- The single enabler: marks the content area as a container so grids reflow on available width (sidebar-aware), not viewport.
  [`App.tsx:784`](../../dashboard/App.tsx#L784)

**Window minimum**

- The user-visible win: lowers the hard floor from 1262 → 720 (sidebar + left-panel min).
  [`main.ts:771`](../../dashboard/electron/main.ts#L771)

**Session reflow**

- Core switch: two-column above 840px container width; single scrolling column (right panel below left) below it.
  [`SessionView.tsx:1288`](../../dashboard/components/views/SessionView.tsx#L1288)
- Stacked-mode correctness: two-column baseline min-height gated behind `@min-[840px]` so it no-ops when stacked.
  [`SessionView.tsx:1326`](../../dashboard/components/views/SessionView.tsx#L1326)

**Notebook reflow**

- Calendar grid switches at 860px container width; below it the page scrolls as one column.
  [`NotebookView.tsx:1168`](../../dashboard/components/views/NotebookView.tsx#L1168)
- Morning/Afternoon stack below the calendar with bounded heights (so `1fr`/`%` rows render) + entrance animation.
  [`NotebookView.tsx:1280`](../../dashboard/components/views/NotebookView.tsx#L1280)

**Animation primitive**

- Reused timing: new `reflowStackIn` keyframe at the project's existing `0.3s cubic-bezier(0.16,1,0.3,1)`; applied `motion-safe` only.
  [`index.css:290`](../../dashboard/src/index.css#L290)
