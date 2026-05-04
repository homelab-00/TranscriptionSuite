---
title: 'Sprint 3 carve-out — Diarization-review bulk-accept undo (Ctrl+Z)'
type: 'feature'
created: '2026-05-04'
status: 'done'
baseline_commit: '9afc6c0'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/sprint-3-design.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sprint 3 Story 5.9 ships `DiarizationReviewView` with bulk-accept
on Space and "Mark all visible as auto-accept best guess" button. Bulk-accept
overwrites every visible turn's decision in one shot — there is no undo. v2
implementation-readiness flagged this as Minor 3 (partially-resolved) and the
deferred-work entry's defense shape names Ctrl+Z as the intended fix.

**Approach:** Add a per-component undo stack scoped to bulk-accept actions.
Before `bulkAccept()` mutates the decisions Map, push the previous Map onto
an `undoStack: Array<Map<number, ReviewDecision>>` (capped at 10 entries to
bound memory). Add an Esc-context-free key handler on the wrapper div that
listens for `Ctrl+Z` (and `Cmd+Z` on macOS) and pops the most recent snapshot
back into `decisions`. Fire `toast.success("Bulk-accept undone — N turns reverted.")`
plus an `announce()` ARIA message. Submit clears the stack (decisions are
final once submitted, per the deferred-work entry).

**Scope discipline:** undo is scoped to **bulk-accept only**, not individual
Enter/Esc decisions. The deferred-work entry is explicit: *"revert the last
bulk-accept within the session"*. The stack stays internal to the component
to avoid coupling with the (currently no-op) ←/→ attribution-cycle UI; the
"could share an undo stack" line in the deferred entry is aspirational.

## Boundaries & Constraints

**Always:**
- Snapshot via `new Map(prev)` BEFORE the bulk-accept overwrites — copy must
  be independent so a later bulk-accept doesn't mutate older snapshots.
- Cap the undo stack at 10 entries; oldest snapshot drops on overflow.
- Ctrl+Z handler must `preventDefault()` so the browser's native undo doesn't
  also fire (the listbox has no contenteditable / form fields, but the
  handler runs at the wrapper which could still bubble to other components).
- Cmd+Z on macOS must work identically — detect via `e.metaKey`.
- Toast message uses `sonner` (`toast.success(...)`) — the project's existing
  pattern (see `dashboard/src/stores/importQueueStore.ts:711`).
- ARIA announcement uses the existing `useAriaAnnouncer` hook already in the
  component.
- Submit (`handleSubmit` → `onComplete`) clears the undo stack — once results
  are sent to the server, the local-only undo affordance is meaningless.

**Ask First:**
- If a redo affordance (Ctrl+Shift+Z / Ctrl+Y) is wanted in addition to undo.
  Default v1: undo only — keeps the keyboard-contract diff small and matches
  the deferred-work entry which only names Ctrl+Z.
- If the toast should be dismissable / stack-aware (multiple consecutive
  undos producing multiple toasts). Default v1: each undo fires its own
  toast; sonner handles the visual stacking.

**Never:**
- Do NOT extend the keyboard contract test rows or PRD §900–920 — Ctrl+Z is
  an additive convenience layer, not part of the canonical contract.
  Document it inside the component docstring only.
- Do NOT persist the undo stack across mounts — the component lifetime is
  the session lifetime, per the deferred-work entry's "in-memory only".
- Do NOT undo individual Enter/Esc decisions. Out of scope.
- Do NOT change `bulkAccept()`'s public effect (still flips every visible
  turn to `accept`); only wrap the call site so the prior Map gets pushed
  onto the stack first.
- Do NOT trap the keystroke when modifier+Z hits with `e.shiftKey` — leave
  Ctrl+Shift+Z untouched (that's reserved for a future redo and we should
  not consume it as a no-op now).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| User presses Ctrl+Z after a single bulk-accept | `undoStack.length === 1`, `decisions` has all visible turns marked `accept` | `decisions` reverts to pre-bulk-accept state; toast + ARIA announce; `undoStack.length === 0` | N/A |
| User presses Ctrl+Z with empty undo stack | `undoStack.length === 0` | No-op (no toast, no ARIA, key event still preventDefault'd) | N/A |
| User bulk-accepts twice, then presses Ctrl+Z | Two snapshots on stack | Reverts to state immediately before second bulk-accept (single undo step); stack now has 1 entry | N/A |
| User presses Cmd+Z on macOS | `e.metaKey === true`, `e.key === 'z'` | Identical to Ctrl+Z | N/A |
| User presses Ctrl+Shift+Z | Reserved for future redo | Handler does NOT consume; key event bubbles | N/A |
| User submits, then presses Ctrl+Z | Stack was cleared on submit | No-op (stack empty) | N/A |
| User clicks the "Mark all visible as auto-accept best guess" button | Same effect as Space/bulkAccept | Pushes snapshot onto stack just like the keyboard path | N/A |
| Filter changes between bulk-accept and undo | `visibleTurns` differs at undo time | Restoring the snapshot still works — `decisions` is keyed by `turn_index`, independent of the current visible set | N/A |
| 11th bulk-accept with stack at cap | `undoStack.length === 10` | Oldest snapshot drops; new one pushed; stack remains at 10 | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/recording/DiarizationReviewView.tsx` — add `undoStack`
  state, wrap `bulkAccept` to snapshot before mutation, add `undoBulkAccept`
  callback, extend `onListKeyDown` AND wrap-div `onKeyDown` to handle Ctrl/Cmd+Z,
  clear stack inside `handleSubmit`, import `toast` from `sonner`. Update the
  component docstring with the Ctrl+Z affordance.
- `dashboard/components/recording/__tests__/DiarizationReviewView.keyboard.test.tsx`
  — add a new `describe` block for "Bulk-accept undo (Ctrl+Z)" covering each
  row of the I/O matrix above. Mock `sonner` `toast.success` to assert the
  call. Reuse the existing `useAriaAnnouncer` mock.

No new files. No public API changes. No CSS class changes (no UI contract
update needed — verified by inspection of the diff plan).

## Tasks & Acceptance

### Task 1 — Tests first (TDD red)

Add tests in `DiarizationReviewView.keyboard.test.tsx`:

1. `Ctrl+Z reverts the most recent bulk-accept` — bulk-accept via Space,
   submit-click captures decisions; reset by render-fresh, bulk-accept,
   Ctrl+Z, then click submit and assert the resulting `onComplete` call has
   no decisions (or all default-fill decisions matching the un-touched
   state).
2. `Cmd+Z behaves identically to Ctrl+Z` — same as above but with
   `metaKey: true` instead of `ctrlKey`.
3. `Ctrl+Z is a no-op when the undo stack is empty` — render, immediately
   Ctrl+Z, submit; result is the default-fill (matches no-bulk-accept
   baseline); `toast.success` is NOT called.
4. `Ctrl+Z only undoes one bulk-accept at a time` — bulk-accept, bulk-accept,
   Ctrl+Z; submit; assert decisions still reflect the FIRST bulk-accept
   (i.e., one pop happened, not full clear).
5. `Ctrl+Shift+Z does not consume the keystroke (reserved for redo)` —
   render, fire keydown with `ctrlKey + shiftKey + 'Z'`, assert that the
   event was NOT preventDefault'd (or assert a marker; an alternative is to
   assert that no toast fired).
6. `submit clears the undo stack` — bulk-accept, submit (with mocked
   onComplete that resolves), then Ctrl+Z; assert no toast call and no
   visible state change.
7. `bulk-accept via the button button (not Space) also pushes onto the stack`
   — click the "Mark all visible as auto-accept best guess" button, then
   Ctrl+Z; assert toast and reverted state.

**AC for Task 1:** All seven tests are written and FAIL on baseline `9afc6c0`
(or pass tautologically only if they're already implemented in `DiarizationReviewView`,
which they shouldn't be). Run `cd dashboard && npm run test -- DiarizationReviewView.keyboard`
and confirm 7 new failures (or some subset failing meaningfully).

### Task 2 — Implementation (TDD green)

In `DiarizationReviewView.tsx`:

1. Add state: `const [undoStack, setUndoStack] = useState<Map<number, ReviewDecision>[]>([])`.
2. Wrap `bulkAccept`:

   ```tsx
   const bulkAccept = useCallback(() => {
     setDecisions((prev) => {
       setUndoStack((stack) => {
         const next = [...stack, new Map(prev)];
         return next.length > 10 ? next.slice(-10) : next;
       });
       const next = new Map(prev);
       for (const t of visibleTurns) {
         next.set(t.turn_index, {
           turn_index: t.turn_index,
           decision: 'accept',
           speaker_id: t.speaker_id,
         });
       }
       return next;
     });
     announce(`Bulk-accepted ${visibleTurns.length} turns.`);
   }, [visibleTurns, announce]);
   ```

3. Add `undoBulkAccept`:

   ```tsx
   const undoBulkAccept = useCallback(() => {
     setUndoStack((stack) => {
       if (stack.length === 0) return stack;
       const previous = stack[stack.length - 1];
       setDecisions(previous);
       const reverted = visibleTurns.length;
       toast.success(`Bulk-accept undone — ${reverted} turn${reverted === 1 ? '' : 's'} reverted.`);
       announce('Bulk-accept undone.');
       return stack.slice(0, -1);
     });
   }, [announce, visibleTurns.length]);
   ```

4. In `onListKeyDown`, add Ctrl/Cmd+Z branch BEFORE the existing switch (so
   Ctrl+Z works while listbox has focus):

   ```tsx
   if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'z' || e.key === 'Z')) {
     e.preventDefault();
     undoBulkAccept();
     return;
   }
   ```

5. Add a parallel handler at the wrapping `<div>` for Ctrl+Z when the
   listbox does not own focus (so the user can press it from the
   filter dropdown / submit button area). Same predicate.

6. In `handleSubmit`, clear the stack: `setUndoStack([])` before or after
   `await onComplete(...)` (after, so a thrown await doesn't drop the stack
   inadvertently — but submit failure is rare and the stack-clear is
   idempotent either way; pick AFTER for safety).

7. Import `toast` from `sonner` at the top.

8. Extend the component-level docstring (lines 1–21) with one bullet:
   "Ctrl+Z (Cmd+Z) — undo the most recent bulk-accept (in-memory only;
    cleared on submit)."

**AC for Task 2:** All Task 1 tests pass. Run `cd dashboard && npm run test -- DiarizationReviewView.keyboard`
and assert green. Run the full vitest suite to confirm no regressions.

### Task 3 — Verify and ship

1. `cd dashboard && npm run typecheck` — must pass.
2. `cd dashboard && npm run test -- DiarizationReviewView` — green.
3. UI contract: no CSS class additions/removals expected. If `npm run ui:contract:check`
   from `dashboard/` flags any drift, it indicates a regression and must be
   investigated (not auto-baselined).
4. Update `_bmad-output/implementation-artifacts/deferred-work.md`:
   delete the Sprint 3 Item 2 (bulk-accept undo) entry per the file's
   "When an item ships, **delete the entry**" rule.

## Spec Change Log

- 2026-05-04: Initial draft (status: in-progress).
- 2026-05-04: Implementation landed; status → done. Added 7 keyboard-contract
  tests (all green; full suite 1219/1220 passing — single failure is a
  pre-existing flaky `installerCache.test.ts` filesystem-timing test that
  passes in isolation). Discovered during implementation: keydown events
  bubble from the listbox to the wrapper handler — required
  `e.stopPropagation()` on the listbox's Ctrl+Z branch so the wrapper
  handler doesn't undo a second time when focus is on the listbox.

## Design Notes

**Why undoStack.slice(-10) for cap?** The deferred entry doesn't specify a
cap, and pragmatically a user who bulk-accepts more than 10 times in one
review session is doing something unusual. 10 is generous, bounded, and
inexpensive (each Map snapshot is at most O(visibleTurns) entries —
typically <100).

**Why cap rather than infinite history?** Memory hygiene + the deferred
entry's "in-memory only" framing implies a session-lifetime affordance, not
a full transactional history.

**Why the predicate `!e.shiftKey`?** Reserves Ctrl+Shift+Z for a future
redo affordance. The deferred entry doesn't request redo, so this spec
doesn't add it — but consuming Ctrl+Shift+Z now (and silently doing
nothing) would later require breaking change.

**Why on both the listbox and the wrapper?** The keyboard contract gives
the listbox the only "hot" focus inside the view. But after a bulk-accept,
the user might naturally tab to the "Run summary now" button before
deciding to undo. Catching Ctrl+Z at the wrapper preserves discoverability.

**Sharing the stack with future ←/→ attribution-cycle?** The deferred
entry mentions this aspirationally. Defer until ←/→ does something — at
which point the stack can be widened to a discriminated-union of action
types (`{type: 'bulk_accept'} | {type: 'attribution_cycle', ...}`). For now
keeping the stack scoped to bulk-accept Maps keeps types simple.
