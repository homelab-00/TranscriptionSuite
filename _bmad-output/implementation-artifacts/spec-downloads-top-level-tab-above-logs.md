---
title: 'Promote Downloads To Top-Level Sidebar Tab'
type: 'feature'
created: '2026-03-31'
status: 'done'
baseline_commit: 'b16e113'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Downloads is currently nested as a Logs sub-tab, which makes it harder to discover and inconsistent with the main sidebar navigation model.

**Approach:** Promote Downloads to a first-class top-level sidebar item and place it directly above Logs, while keeping Logs focused on system log output and preserving existing Downloads panel behavior.

## Boundaries & Constraints

**Always:**
- Keep Downloads as a dedicated full tab in the primary sidebar, ordered immediately above Logs.
- Route Downloads to the existing downloads UI panel and data store behavior.
- Keep Logs as its own full tab for log terminal content.
- Preserve current sidebar visual style, spacing, status indicators, and collapse behavior.

**Ask First:**
- Changing labels, iconography, or naming beyond the requested placement change.
- Any scope expansion into filtering, sorting, or behavior changes inside the Downloads panel.

**Never:**
- Change download tracking/store semantics.
- Change backend/electron IPC or server behavior for logs or downloads.
- Introduce unrelated sidebar reorganization.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open Downloads from sidebar | User clicks top-level Downloads item | Main content switches to Downloads panel, Downloads nav item is active, Logs is inactive | N/A |
| Open Logs from sidebar | User clicks top-level Logs item | Main content switches to system logs view, log streaming behavior remains intact | N/A |
| Sidebar collapsed | Sidebar is collapsed and user clicks Downloads icon | App still navigates to Downloads view and active selection updates correctly | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/types.ts` -- Top-level view enum and tab enums used by routing/sidebar.
- `dashboard/App.tsx` -- Root view routing and sidebar prop wiring.
- `dashboard/components/Sidebar.tsx` -- Sidebar top-level item order and sub-item rendering.
- `dashboard/components/views/LogsView.tsx` -- Logs-only rendering and stream lifecycle.
- `dashboard/components/views/DownloadsPanel.tsx` -- Existing Downloads screen to be reused as-is.

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/types.ts` -- add a dedicated top-level Downloads view identifier and remove/deprecate logs sub-tab coupling -- enables direct routing.
- [x] `dashboard/App.tsx` -- route top-level Downloads view to `DownloadsPanel`, and simplify Logs view wiring to logs-only -- aligns runtime behavior with new nav hierarchy.
- [x] `dashboard/components/Sidebar.tsx` -- move Downloads into `navItems` directly above Logs and remove Logs sub-tab rendering for Downloads -- implements requested sidebar structure.
- [x] `dashboard/components/views/LogsView.tsx` -- remove Downloads branch and keep this view strictly logs-focused -- prevents hidden coupling after nav change.
- [x] `dashboard` -- run typecheck and UI contract check -- verify UI and type safety after navigation changes.

**Acceptance Criteria:**
- Given the app is running, when the user views the sidebar, then Downloads appears as a full top-level tab directly above Logs.
- Given the user clicks Downloads, when navigation updates, then the Downloads panel renders with current download data and Logs is not required as a parent tab.
- Given the user clicks Logs, when Logs renders, then system logs view remains available and continues to behave as before.
- Given the sidebar is collapsed, when the user navigates via icons, then Downloads and Logs remain independently navigable.

## Spec Change Log

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` -- expected: TypeScript passes without new errors.
- `cd dashboard && npm run ui:contract:check` -- expected: Contract validation/tests pass or intentional delta is surfaced for explicit acceptance.

## Suggested Review Order

**Routing and View Ownership**

- Introduces dedicated top-level Downloads route and decouples Logs from sub-tab state.
	[`App.tsx:1`](../../dashboard/App.tsx#L1)

- Adds Downloads to global view enum and removes legacy Logs sub-tab enum.
	[`types.ts:1`](../../dashboard/types.ts#L1)

**Sidebar Navigation Structure**

- Places Downloads immediately above Logs as a first-class nav item.
	[`Sidebar.tsx:152`](../../dashboard/components/Sidebar.tsx#L152)

- Removes Logs-only sub-tab rendering now that Downloads is top-level.
	[`Sidebar.tsx:334`](../../dashboard/components/Sidebar.tsx#L334)

**Logs and Downloads View Boundaries**

- Makes LogsView logs-only and removes Downloads conditional branch.
	[`LogsView.tsx:1`](../../dashboard/components/views/LogsView.tsx#L1)

- Updates panel docs to reflect top-level sidebar placement.
	[`DownloadsPanel.tsx:1`](../../dashboard/components/views/DownloadsPanel.tsx#L1)
