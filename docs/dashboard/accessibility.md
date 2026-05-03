# Dashboard Accessibility Conventions

Established by Issue #104 Story 1.8; consumed by every downstream UI story
(3.5, 4.3, 4.4, 5.7, 5.9, 6.6, 8.2, etc.) via inheritance.

## ARIA-live announcements

Two regions live at the app root (`<AriaLiveRegion />`):

- `role="status" aria-live="polite"` — wait for current speech
- `role="status" aria-live="assertive"` — interrupt immediately

Push an announcement from any component:

```tsx
import { useAriaAnnouncer } from '@/hooks/useAriaAnnouncer';

function CompletedToast() {
  const announce = useAriaAnnouncer();
  useEffect(() => announce('Transcription complete'), [announce]);
  return null;
}
```

For interrupting messages (failures, network loss):

```tsx
announce('Network connection lost', { politeness: 'assertive' });
```

The store clears each region 5 s after a write so identical messages
can re-announce (assistive technologies otherwise coalesce repeats).

## Tab-order convention — completed-recording detail view

Canonical order, top to bottom:

1. **Status banners** (persistent, non-dismissable — UX-DR2)
2. **Status badges** (per-action: summary, export, webhook — UX-DR1)
3. **Transcript view** (single tab stop; arrow keys move within turns)
4. **AI summary panel**
5. **Download buttons** (transcript → summary → audio)

New components MUST follow this order. If you must diverge, leave a
`/* tab-order divergence: <reason> */` comment at the top of the
component so reviewers can audit.

## Descriptive button labels (FR53)

Never ship a bare action verb: `<button>Download</button>` is a screen
reader's worst case. Use the helpers in `src/utils/a11yLabels.ts`:

```tsx
import { downloadButtonLabel } from '@/utils/a11yLabels';

<button aria-label={downloadButtonLabel('transcript')}>Download</button>
```

This keeps label vocabulary consistent across the dashboard. ESLint's
`jsx-a11y/control-has-associated-label` flags missing labels at lint
time.

## Keyboard activation (FR51)

- Buttons MUST work with both Enter and Space (default `<button>`
  behaviour — don't override `onKeyDown` unless you know what you're
  doing).
- Folder picker, modal close, etc. MUST be reachable without a mouse.
- After a dialog dismisses, focus returns to the triggering element
  (Electron handles this for native dialogs; for custom modals, use
  React's ref pattern in the modal host).

## Manual screen-reader smoke test (NFR25 / NFR26)

Before each MVP-cut PR, the reviewer runs (and pastes results in the PR):

- **NVDA on Windows 11** — open the app, navigate to a completed
  recording, verify status badges and download buttons are announced
  with descriptive labels.
- **Orca on Linux KDE Wayland** — same flow.

Tag the PR with `@review/manual-a11y` so the workflow knows to wait
for the manual sign-off comment.

## Why no Lighthouse CI yet

Story 1.8 deferred Lighthouse-CI wiring (against Vite preview) as a
documented choice — the gate adds ~90 s + ~40 MB CI weight (NFR25
acknowledges) and Vite-preview wiring proved brittle in spike. ESLint
`jsx-a11y` rules cover the lint-time portion of the AC. The full
Lighthouse gate is captured in `_bmad-output/implementation-artifacts/deferred-work.md`
and slated for the MVP-cut PR.
