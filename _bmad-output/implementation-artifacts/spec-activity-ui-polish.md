---
title: 'Activity System — UI Polish (Phase 5)'
type: 'feature'
created: '2026-04-01'
status: 'done'
baseline_commit: '929c498'
context:
  - 'docs/project-context.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The Activity panel and floating notifications are functional but lack polish: completed items show no timing, download events show no byte counts, expandable details are invisible, auto-dismiss uses a single 5-second timeout for all categories, and the notification preference toggles (already wired in the store) have no UI.

**Approach:** Surface the existing data fields (`durationMs`, `downloadedSize`/`totalSize`, `expandableDetail`) in the ActivityPanel with expandable rows. Add category-specific auto-dismiss rules to ActivityNotifications. Wire the existing `notificationPreferences` store to a new section in SettingsModal with per-category toggles.

## Boundaries & Constraints

**Always:**
- Use existing `activityStore` fields and actions — no store schema changes needed
- Match existing design language (Tailwind utility classes, lucide-react icons, shadcn-style patterns)
- Persist notification preferences via the existing localStorage mechanism in activityStore

**Ask First:**
- If any new npm dependencies are needed (should not be — Tailwind + lucide covers this)

**Never:**
- Add React state management libraries (Zustand store already handles this)
- Change the event protocol or startup_events.py
- Remove or break existing functionality (legacy download type rendering, progress bars)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Expandable row clicked | Item has `expandableDetail` | Detail section toggles open/closed below the item | N/A |
| Item has no expandable detail | `expandableDetail` is undefined | No expand affordance shown | N/A |
| Completed server item | `status:"complete"`, `durationMs:4200` | Inline timing badge: "4.2s" | N/A |
| Active download item | `progress:34`, `downloadedSize`, `totalSize` | Progress bar + "720 MB / 2.1 GB" size text | N/A |
| Notification pref toggled off | User disables "Server" category | Server events hidden from floating widget; still visible in Activity panel | N/A |
| Persistent warning | `persistent:true` | Never auto-dismissed regardless of category timeout | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/stores/activityStore.ts` -- Existing store with notificationPreferences (no changes needed)
- `dashboard/components/views/ActivityPanel.tsx` -- Add expandable rows, inline timing, download size display
- `dashboard/components/ui/ActivityNotifications.tsx` -- Category-specific auto-dismiss durations
- `dashboard/components/views/SettingsModal.tsx` -- Add "Floating Notifications" section with per-category toggles

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/views/ActivityPanel.tsx` -- Add expandable detail: when an item has `expandableDetail`, show a chevron toggle that reveals/hides the detail text below the item row. Add inline timing: for completed items with `durationMs`, show a small badge (e.g., "4.2s"). Add download size: for download items with `totalSize`, show formatted bytes (e.g., "720 MB / 2.1 GB") below the progress bar.
- [x] `dashboard/components/ui/ActivityNotifications.tsx` -- Replace single `AUTO_DISMISS_MS` constant with per-category durations: server 5s, download 5s, info 10s, warning (non-persistent) 10s. Persistent items never auto-dismiss (already handled).
- [x] `dashboard/components/views/SettingsModal.tsx` -- Add "Floating Notifications" section in the App tab with 4 toggle switches (Downloads, Server Status, Warnings, Info) reading from and writing to `activityStore.notificationPreferences` via `setNotificationPreference()`. Include helper text: "Controls floating widget only — Activity panel always shows all events."

**Acceptance Criteria:**
- Given an item with `expandableDetail`, when the user clicks the expand toggle, then the detail text appears below the item
- Given a completed item with `durationMs: 4200`, when rendered in the panel, then "4.2s" appears inline
- Given a server-category notification, when it completes, then it auto-dismisses after 5 seconds
- Given an info-category notification, when it completes, then it auto-dismisses after 10 seconds
- Given the user disables "Server" in notification preferences, when a server event fires, then it appears in the Activity panel but not in the floating widget

## Verification

**Commands:**
- `cd dashboard && npm run build` -- expected: no TypeScript errors
- `cd dashboard && npm run ui:contract:check` -- expected: no contract violations (if CSS classes changed)

**Manual checks:**
- Toggle expand on an item with expandableDetail — verify reveal/hide works
- Check timing badge on completed events
- Toggle notification prefs in settings — verify floating widget respects them

## Suggested Review Order

**ActivityPanel — expandable rows, timing, size display**

- Expandable detail toggle: chevron replaces icon when item has `expandableDetail`
  [`ActivityPanel.tsx:162`](../../dashboard/components/views/ActivityPanel.tsx#L162)

- Inline timing badge for completed items with `durationMs`
  [`ActivityPanel.tsx:189`](../../dashboard/components/views/ActivityPanel.tsx#L189)

- Download size display using pre-formatted strings from store
  [`ActivityPanel.tsx:199`](../../dashboard/components/views/ActivityPanel.tsx#L199)

- Expand state management via `Set<string>` in main panel
  [`ActivityPanel.tsx:279`](../../dashboard/components/views/ActivityPanel.tsx#L279)

**ActivityNotifications — per-category auto-dismiss**

- Category-specific timeout map replacing single constant
  [`ActivityNotifications.tsx:102`](../../dashboard/components/ui/ActivityNotifications.tsx#L102)

**SettingsModal — notification preference toggles**

- FloatingNotificationsSection with 4 AppleSwitch toggles wired to activityStore
  [`SettingsModal.tsx:1613`](../../dashboard/components/views/SettingsModal.tsx#L1613)
