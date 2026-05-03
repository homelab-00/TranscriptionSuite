---
title: 'Simplify Notification System — Remove Activity Panel & Strip Store'
type: 'refactor'
created: '2026-04-04'
status: 'done'
baseline_commit: '0e73f2577bf10f2ec37806c6e7c8caaa8c2c9200'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The activity/notification system was over-engineered with a 4-category model (download, server, warning, info), a full Activity sidebar panel, notification preference toggles, and session grouping — but the only notifications that fire in practice are "downloading runtime" and "loading model" toasts. The sidebar Activity tab is dead weight.

**Approach:** Delete the Activity sidebar panel entirely. Remove notification preferences and category infrastructure. Keep the floating bottom-right toast widget (`ActivityNotifications.tsx`) and the event bridge (`useBootstrapDownloads.ts`) functional — they are the only parts users actually see. Slim the store to what the remaining consumers need.

## Boundaries & Constraints

**Always:**
- Keep floating bottom-right toast notifications working for `download`-category events (runtime deps, model preload, Docker images, sidecar images, ML models)
- Keep `useBootstrapDownloads` hook and both IPC channels (`docker:downloadEvent`, `activity:event`) intact — they are the event sources
- Keep ServerView's direct `useActivityStore` calls working (lines that push download progress for sidecar/model downloads)
- Run `npm run ui:contract:check` from `dashboard/` after all changes

**Ask First:**
- If any other component (not listed in Code Map) imports `activityStore` or `ActivityPanel`

**Never:**
- Do not change the Electron main-process side (dockerManager.ts, startupEventWatcher.ts, preload.ts) — those event sources are correct
- Do not touch ServerView's download tracking logic — only its imports may change if types are renamed
- Do not add new features or notification types

</frozen-after-approval>

## Code Map

- `dashboard/src/stores/activityStore.ts` -- Zustand store; strip notification preferences, session management, unused selectors
- `dashboard/components/views/ActivityPanel.tsx` -- Full sidebar Activity view; DELETE entirely
- `dashboard/components/ui/ActivityNotifications.tsx` -- Floating toast widget; simplify icon/color mapping, remove category-based filtering
- `dashboard/components/Sidebar.tsx:177` -- Activity nav item; DELETE entry
- `dashboard/types.ts:6` -- `View.ACTIVITY` enum member; DELETE
- `dashboard/App.tsx:628-633` -- `View.ACTIVITY` case in view switch; DELETE case + import
- `dashboard/App.tsx:83` -- `useBootstrapDownloads()` mount; KEEP as-is
- `dashboard/components/views/SettingsModal.tsx:459,1654-1682` -- `FloatingNotificationsSection`; DELETE section + import

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/ActivityPanel.tsx` -- DELETE file -- no longer needed
- [x] `dashboard/types.ts` -- Remove `ACTIVITY` from `View` enum -- dead sidebar view
- [x] `dashboard/App.tsx` -- Remove `View.ACTIVITY` case, `ActivityPanel` import -- dead route
- [x] `dashboard/components/Sidebar.tsx` -- Remove Activity nav entry (id: View.ACTIVITY) -- dead tab
- [x] `dashboard/components/views/SettingsModal.tsx` -- Delete `FloatingNotificationsSection` component and its render call (line 459), remove `useActivityStore`/`ActivityCategory` imports -- preferences for deleted categories
- [x] `dashboard/src/stores/activityStore.ts` -- Remove: `notificationPreferences`, `setNotificationPreference`, `loadPreferences`, `savePreferences`, `clearSession`, `setSessionId`, `sessionId` from store. Remove `ActivityCategory` type (inline `'download'` where needed). Remove `clearAll` (only ActivityPanel used it). Keep: `addActivity`, `updateActivity`, `dismissActivity`, `items`, `selectVisibleNotifications`, `selectActiveItems`, `selectHasActiveItems`
- [x] `dashboard/components/ui/ActivityNotifications.tsx` -- Remove `CATEGORY_ICON`, `CATEGORY_COLOR` maps and category-preference filtering. Keep `LEGACY_TYPE_ICON`/`LEGACY_TYPE_COLOR` for download items. Show all non-dismissed items unconditionally
- [x] `dashboard/components/views/ServerView.tsx` -- Update imports if `ActivityCategory` type is removed (replace with inline `'download'` string literal in addActivity calls) — no change needed, ServerView already used string literal 'download' and didn't import ActivityCategory

**Acceptance Criteria:**
- Given the app loads, when the sidebar renders, then there is no "Activity" tab
- Given a runtime dependency install fires, when the bootstrap log parser emits the event, then a floating toast appears bottom-right and auto-dismisses after completion
- Given a model preload fires, when the event reaches the store, then a floating toast with spinner appears and completes normally
- Given the Settings modal opens, then there is no "Floating Notifications" preferences section
- Given `npm run ui:contract:check` runs from `dashboard/`, then it passes with no errors

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no type errors
- `cd dashboard && npm run ui:contract:check` -- expected: pass (or regenerate baseline if CSS classes changed)

**Manual checks:**
- Start the app, confirm no Activity tab in sidebar
- Trigger a model preload or runtime dep install, confirm floating toast appears bottom-right
- Open Settings, confirm no notification preferences section

## Suggested Review Order

**Store simplification (entry point)**

- Store stripped to download-only: removed preferences, sessions, clearAll, ActivityCategory
  [`activityStore.ts:1`](../../dashboard/src/stores/activityStore.ts#L1)

- Category cast hardcoded to 'download' since non-download events never fire
  [`useBootstrapDownloads.ts:59`](../../dashboard/src/hooks/useBootstrapDownloads.ts#L59)

**Dead UI removal**

- ActivityPanel.tsx deleted entirely (333 lines)

- ACTIVITY member removed from View enum
  [`types.ts:1`](../../dashboard/types.ts#L1)

- View.ACTIVITY case and ActivityPanel import removed
  [`App.tsx:624`](../../dashboard/App.tsx#L624)

- Activity nav entry and History icon import removed
  [`Sidebar.tsx:172`](../../dashboard/components/Sidebar.tsx#L172)

- FloatingNotificationsSection + useActivityStore/ActivityCategory imports removed
  [`SettingsModal.tsx:458`](../../dashboard/components/views/SettingsModal.tsx#L458)

**Floating widget refinement**

- CATEGORY_ICON/COLOR maps removed; uses selectVisibleNotifications selector; AUTO_DISMISS_MS simplified
  [`ActivityNotifications.tsx:20`](../../dashboard/components/ui/ActivityNotifications.tsx#L20)

**Contract baseline**

- UI contract regenerated after ActivityPanel removal
  [`transcription-suite-ui.contract.yaml`](../../dashboard/ui-contract/transcription-suite-ui.contract.yaml)
