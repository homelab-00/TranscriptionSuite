---
title: 'Blur-surface tier audit (GH-87 Wave 4 / E89)'
type: 'audit'
created: '2026-06-01'
baseline_commit: '261ccb7'
status: 'complete'
scope: 'dashboard backdrop-blur surfaces — design-decision input, NOT an implementation'
context:
  - '_bmad-output/brainstorming/brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md'
  - '_bmad-output/implementation-artifacts/deferred-work.md'
  - 'dashboard/ui-contract/design-language.md'
  - 'dashboard/ui-contract/transcription-suite-ui.contract.yaml'
---

## What this is (and is not)

This is the **E89 deliverable** from the Issue-87 Mac-idle RCA (brainstorming doc, Wave 4 / Cluster I):
a one-pass classification of **every** `backdrop-blur` surface in the dashboard into fidelity tiers
**T1–T4**, with the **decided per-surface action** each tier implies.

It is **decision input, not a code change.** No blur was added, removed, or altered to produce it.
It exists so that the moment a per-surface demotion is greenlit (see "What unblocks this"), the
work is "execute the recorded action" instead of "start the analysis cold."

**Why it could be produced now, with no Apple Silicon Mac:** classification is static analysis of
local source. It changes zero shipped pixels and needs neither a Mac nor designer-produced assets.
**Every *demotion* the table recommends, however, remains gated** — the GPU magnitudes are
RCA-predicted (never measured) and the visual acceptability of any reduced surface can only be judged
on a Retina/Metal display. This audit records the decisions; it does not authorize executing them.

## Verified inventory (supersedes earlier counts)

Authoritative as of `261ccb7` (`rg 'backdrop-blur'` over `dashboard/{components,src,App.tsx,index.tsx}`,
excluding tests):

- **61 `backdrop-blur` utility call-sites across 21 component/`src` files.**
- Plus the CSS control layer in `dashboard/src/index.css`: 1 token (`--backdrop-blur-xs: 2px`) and
  2 paired `backdrop-filter: none` kill-switches (blur-effects-off at L105-106, low-idle at L123-124).

Earlier numbers were wrong and should not be reused:

| Source | Claimed | Reality |
|--------|---------|---------|
| deferred-work.md / spec-gh-87-low-idle-usage-toggle.md | "21 files / 36 call-sites" | **61 sites / 21 files** |
| Low-idle handoff | "~54 blur sites" | **61 sites / 21 files** |
| Wave-4 investigation subagent | "57 sites / 21 files" | arithmetic slip; per-file counts summed to 61 |

The grandfathered `blur_depth_budgets` per-file ceilings in the contract **exactly equal** current
usage (Σ overrides + defaults = 61), i.e. every file currently sits *at* its budget. Any new
`backdrop-blur` fails `npm run ui:contract:check` — the budget is a freeze, not headroom.

Note: the deferred-work doc's `--glass-fidelity` premise is **incorrect** — no such token exists.
Blur today is a **binary on/off escape valve** (the two kill-switches above), not a graded multiplier.
A graded token is candidate **E126**, which is *not* part of this audit.

## Tier vocabulary

The RCA's F1 ("codify T1–T4 tiers in `design-language.md`") was **never shipped** — `design-language.md`
has prose principles but no formal taxonomy and no `--blur-t1..t4` tokens. This audit therefore states
the vocabulary it classifies against, taken from the RCA F1 decision (brainstorming doc L1779-1783).
Each tier encodes both a *role* and the *target treatment* (so the tier IS the action):

| Tier | Role | Target treatment | Action implied |
|------|------|------------------|----------------|
| **T1** | Focal modal glass — one visible at a time | Full glass, `backdrop-blur-xl` (24px) | **Keep** |
| **T2** | Card / persistent-panel glass — many can be visible | Reduced, `backdrop-blur-md` (12px) | **Reduce radius** xl→md |
| **T3** | Ambient chrome — peripheral, always-on | Tinted only — *no* `backdrop-filter`; `bg-* + backdrop-saturate` | **Demote to tinted** |
| **T4** | Utility / decorative | Solid or gradient only — no blur | **Drop blur** |

Cross-cutting reductions referenced below (all from the RCA): **E35** drop modal-scrim blur (opaque
dim suffices), **E60** drop blur on small surfaces (<~200px², imperceptible), **E22/F3** flatten nested
blur, **E14** `backdrop-blur-3xl`→`xl + brightness`, **E82** demote the Sidebar, **E36/F4** drop the
scroll-edge fade blur.

## Per-surface classification

Action legend: **KEEP** = full glass (T1); **REDUCE** = xl→md (T2); **TINT** = drop blur for
tinted-only (T3); **DROP** = remove blur (T4 / scrim / small-surface). All non-KEEP actions are
**Mac-gated** unless flagged otherwise.

### Modal & dialog panels — KEEP (T1)

The legitimately focal glass; only one is visible at a time, so per-frame cost is bounded. No change.

| File:line | Class | Surface |
|-----------|-------|---------|
| App.tsx:832, :907, :944, :1022 | `backdrop-blur-xl` | 4 root-level modal panels (mutually exclusive) |
| AudioNoteModal.tsx:1832, :1875 | `backdrop-blur-xl` | 2 confirm sub-dialog panels |
| AudioNoteModal.tsx:1923 | `backdrop-blur-xl` | Main audio-note panel (focal — E85: promote/keep T1) |
| SettingsModal.tsx:2269 | `backdrop-blur-xl` | Settings panel |
| ServerView.tsx:2753, :2846 | `backdrop-blur-xl` | 2 confirm-dialog panels |
| AboutModal.tsx:84 · BugReportModal.tsx:110 · StarPopupModal.tsx:70 · GpuDiagnosticModal.tsx:206 · UpdateModal.tsx:371 · AddNoteModal.tsx:334 | `backdrop-blur-xl` | Modal panels |
| useConfirm.tsx:45 · DedupPromptModal.tsx:59 · DeleteRecordingDialog.tsx:48 | `backdrop-blur-xl` | Shared confirm/dialog panels |

### Modal scrims — DROP blur (E35), keep opaque dim

Each modal pairs its panel with a full-screen scrim carrying `backdrop-blur-sm` (or `-md`). The scrim
already dims via `bg-black/40–70`; the blur on a transient, about-to-be-covered backdrop is the
**lowest-risk reduction in the whole app**. Visual call still Mac-gated, but the blast radius is minimal.

| File:line | Class | Note |
|-----------|-------|------|
| App.tsx:823, :904, :941, :1019 | `backdrop-blur-sm` | 4 root modal scrims |
| AudioNoteModal.tsx:1829, :1872 | `backdrop-blur-sm` | confirm scrims |
| AudioNoteModal.tsx:1917 | `backdrop-blur-md` | main-modal scrim (heavier — `md`) |
| ServerView.tsx:2751, :2844 | `backdrop-blur-sm` | confirm scrims |
| AboutModal.tsx:78 · BugReportModal.tsx:104 · StarPopupModal.tsx:64 · GpuDiagnosticModal.tsx:201 · UpdateModal.tsx:365 · SettingsModal.tsx:2263 · AddNoteModal.tsx:328 | `backdrop-blur-sm` | modal scrims |
| useConfirm.tsx:43 · DedupPromptModal.tsx:57 · DeleteRecordingDialog.tsx:46 | `backdrop-blur-sm` | shared scrims |

### Small surfaces — DROP blur (E60, imperceptible)

| File:line | Class | Surface |
|-----------|-------|---------|
| AboutModal.tsx:95 · BugReportModal.tsx:124 · StarPopupModal.tsx:80 · GpuDiagnosticModal.tsx:225 · UpdateModal.tsx:392 | `backdrop-blur-md` | round close-buttons (~32px) |
| BugReportModal.tsx:145 | `backdrop-blur-sm` | textarea input — also **nested** inside the blurred panel (redundant) |
| Button.tsx:22 | `backdrop-blur-md` | `glass` button variant (small surfaces) |
| Button.tsx:19 | `backdrop-blur-xs` (2px) | `secondary` variant — **negligible; keep** |

### Cards & panels — REDUCE (T2)

| File:line | Class | Surface | Action |
|-----------|-------|---------|--------|
| GlassCard.tsx:18 | `backdrop-blur-xl` | **Ubiquitous card** — reused across all views | REDUCE xl→md (highest-multiplicity surface) |
| ActivityNotifications.tsx:97 | `backdrop-blur-xl` | Toast card | REDUCE |
| AudioNoteModal.tsx:2335 | `backdrop-blur-xl` | Sticky transcript-header pill | REDUCE / small-surface |
| FindReplaceToolbar.tsx:36, :75 | `backdrop-blur` (8px) | Toggle button + toolbar panel | REDUCE / small |
| NotebookView.tsx:441, :610 | `backdrop-blur-xl` | Context menu + popover (transient overlays) | REDUCE |

### Ambient chrome — DEMOTE to tinted (T3)

| File:line | Class | Surface | Action |
|-----------|-------|---------|--------|
| **Sidebar.tsx:234** | **`backdrop-blur-2xl` (40px)** | Full-height, always-visible persistent chrome | **TINT (E82) — single most expensive + least focal blur; top demotion target** |
| NotebookView.tsx:808 (+ :810) | `backdrop-blur-xl` container **nesting** `backdrop-blur-md` header | Panel container + sticky header | **FLATTEN (E22/F3): keep header `md`, demote container to tinted** — A3 nested-blur antipattern |

### Decorative / idle — DROP or sharply REDUCE (T4)

| File:line | Class | Surface | Action |
|-----------|-------|---------|--------|
| SessionView.tsx:1296, :1919, :1944, :2317 | `bg-linear-* + backdrop-blur-sm` | 4 scroll-edge fade masks | **DROP blur, keep gradient (E36/F4)** — ⚠ **see design-language conflict below** |
| FullscreenVisualizer.tsx:50 | `backdrop-blur-3xl` (64px, max) | Transient fullscreen backdrop | REDUCE 3xl→xl+brightness (E14) — transient, low-risk |

### CSS control layer — not a visual surface

`src/index.css:21` (`--backdrop-blur-xs` token), `:105-106` (blur-effects-off kill-switch),
`:123-124` (low-idle kill-switch). These are the central control surface, not per-component blur.
The shipped **Low idle usage** toggle already nulls *all* of the above app-wide when ON.

## Tallies by action

| Action | Count | Risk of executing (when greenlit) |
|--------|------:|-----------------------------------|
| **KEEP** (T1 focal panels) | ~20 | n/a |
| **DROP scrim blur** (E35) | ~17 | Lowest — transient, opaque dim already present |
| **DROP small-surface blur** (E60) | ~8 | Low — imperceptible by definition |
| **REDUCE** xl→md (T2) | ~8 | Medium — GlassCard touches every view; needs look-check |
| **TINT / flatten** (T3) | 2 (Sidebar, NotebookView) | Medium — visible identity change |
| **DROP / reduce decorative** (T4) | 5 | Mixed — FullscreenVisualizer low; scroll-fades blocked by design-language |

## Conflicts & gotchas this audit surfaces

1. **Scroll-edge fades are design-language-protected.** `design-language.md:25-29` *mandates* "Blur
   Bars MUST use `backdrop-blur-sm` with a linear-gradient mask." The RCA's F4/E36 calls dropping them
   a free win — but it is **not** free: it requires amending `design-language.md` first. Owner decision,
   not a silent edit. (Contract `reason:` for SessionView's budget-of-4 also cites this rule.)
2. **Highest-leverage single demotion is the Sidebar** (`backdrop-blur-2xl`, full-height, always
   visible, peripheral) — the most expensive *and* least focal blur in the app (E82).
3. **GlassCard is the highest-multiplicity surface** — one `xl` definition rendered as N cards. A single
   xl→md edit there has outsized aggregate effect but touches every view's look.
4. **One genuine nested-blur (A3) remains:** NotebookView container(`xl`) wrapping header(`md`). The
   `blur_depth_budgets` rule caps *count per file*, not *nesting depth* — RCA F8's `nested_blur_detected`
   rule was never shipped, so this isn't caught automatically.
5. **Budgets are frozen at current usage**, so any demotion must also *lower* the affected file's
   `blur_depth_budgets` override (and re-run the contract update sequence) or the freeze drifts upward.

## What unblocks executing this (i.e. what still needs a Mac / a decision)

The audit is done. Turning any **non-KEEP** row into code requires one of:

- **A Mac reporter measurement** confirming the shipped **Low idle usage** toggle is insufficient
  (deferred-work trigger), since blur-off already captures the dominant lever cross-platform; OR
- **An explicit owner design decision** for the rows that change the look on *all* platforms
  (Linux is primary) — chiefly the GlassCard radius reduction, the Sidebar tinting, and the
  design-language amendment for scroll-edge fades.

Lowest-risk first tranche when greenlit (no design-language change, minimal visual delta):
**scrim-blur drops (E35) + small-surface drops (E60) + FullscreenVisualizer E14** — these touch only
transient/tiny/decorative surfaces. The identity-shifting rows (Sidebar T3, GlassCard T2, scroll-edge
fades) are a separate, explicitly design-gated tranche.

## Status

E89 (this classification) is **complete**. All other Wave-4 candidates (E126, E48/E74/E127, E31/E32,
E59/E92) and native vibrancy (E95) remain as recorded in `deferred-work.md`. Executing any demotion
from this table is **out of scope** here and stays Mac-/decision-gated.
