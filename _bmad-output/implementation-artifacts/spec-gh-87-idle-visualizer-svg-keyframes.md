---
title: 'Restore idle AudioVisualizer character via SVG/CSS keyframes (Issue #87 — Cluster 1 follow-up)'
type: 'feature'
created: '2026-04-26'
status: 'done'
baseline_commit: 'f138b37c4fc45d08a828940eb8d1eb1547006273'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After commit `048dba8` ("gate AudioVisualizer rAF on isActive prop"), the `AudioVisualizer` canvas stays blank while no recording is in progress because `isActive` defaults to false and `drawSimulation()` never runs. The project owner explicitly flagged on 2026-04-25 that the layered cyan/magenta/orange idle wave was character-defining UI; its disappearance is a perceived-polish regression even though the gate is a real perf win.

**Approach:** Add a third render branch to `AudioVisualizer` that activates only when `!isActive && !analyserNode` (true idle — no recording, no playback, no live mode). The branch renders an inline SVG with three `<path>` sine waves, each animated via CSS `@keyframes` on `transform` / `opacity` only (compositor-thread, zero per-frame JS). The existing canvas + rAF path for `isActive=true` is unchanged; the existing inactive-with-analyser path (e.g. paused recording, mounted-but-not-playing audio note) stays blank to preserve the gate-87 perf win.

## Boundaries & Constraints

**Always:**
- The component's external API stays unchanged: `className`, `analyserNode`, `amplitudeScale`, `isActive`. Callers do not need to change.
- The SVG branch only renders when `!isActive && !analyserNode` — never when an analyser is attached. This preserves the gate-87 perf win for paused-recording and pre-playback states (where the surrounding UI shows its own "No Input" / paused labels).
- CSS animations target `transform` and `opacity` only — never `width`, `top`, `filter`, or any property that triggers layout/paint. Compositor-thread only.
- Palette must match the legacy `drawSimulation()` palette exactly: `rgba(34,211,238,0.6)`, `rgba(217,70,239,0.5)`, `rgba(251,146,60,0.3)`.
- Animation period is ~4s, infinite, with the three layers offset so their phase relationship reads as "weaving" rather than "synchronized march".
- Honour `@media (prefers-reduced-motion: reduce)`: the SVG paths still render (so the visual character is restored) but with `animation: none`. A static frozen frame is acceptable.
- The SVG must be responsive via `viewBox` + `preserveAspectRatio` — no JS resize listener, no media queries.
- The grid overlay and outer container (`relative w-full overflow-hidden rounded-xl border border-white/5 bg-black/20 shadow-inner`) stay exactly as today; the SVG slots in where the canvas does, behind the same grid overlay.

**Ask First:**
- If the SVG branch ever needs to read `analyserNode` data (it should not), HALT and re-evaluate — that would re-introduce per-frame JS and undo the gate-87 win.
- If the keyframe animation cannot be expressed without a layout-triggering property (e.g. animating `d` directly), HALT and confirm whether to accept the perf cost or drop a layer.

**Never:**
- Do NOT introduce any `requestAnimationFrame`, `setInterval`, or `setTimeout` in the new branch. Declarative CSS only.
- Do NOT add a new `backdrop-blur-*` utility anywhere — the blur-depth budget rule from `spec-gh-87-blur-depth-budget-rule` must continue to pass.
- Do NOT change the canvas/rAF path for `isActive=true` — its behaviour is locked by `spec-gh-87-audiovisualizer-isactive-gate`.
- Do NOT change call sites (`SessionView.tsx`, `FullscreenVisualizer.tsx`, `AudioNoteModal.tsx`). The new branch activates purely on existing prop combinations.
- Do NOT add JS-driven motion preferences. Use the CSS `@media (prefers-reduced-motion: reduce)` rule directly.
- Do NOT introduce a new dependency (no `framer-motion`, no `lottie`, no SVG animation library).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cold mount, no recording | `isActive=false`, `analyserNode=undefined` | SVG branch renders; 3 colored paths animate on a ~4s loop via CSS keyframes | N/A |
| Paused recording (analyser mounted, gate off) | `isActive=false`, `analyserNode=AnalyserNode` | NO SVG, NO canvas paint — stays blank (gate-87 perf win preserved) | N/A |
| Active recording / live mode | `isActive=true`, `analyserNode=AnalyserNode` | Existing canvas branch paints `drawReal()` via rAF — unchanged | N/A |
| Active without analyser (degenerate) | `isActive=true`, `analyserNode=undefined` | Existing canvas branch paints `drawSimulation()` via rAF — unchanged | N/A |
| User has `prefers-reduced-motion: reduce` | `isActive=false`, `analyserNode=undefined`, OS reduce-motion ON | SVG paths render (visual character restored) but `animation: none` — static frame | N/A |
| Container resize | Parent element width/height changes while idle SVG visible | SVG scales smoothly via `viewBox`; no JS listener fires | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/AudioVisualizer.tsx` — add the third render branch (`!isActive && !analyserNode` → return SVG element). Conditional render in JSX, before the existing `<canvas>`. The canvas stays in the tree under the other branches.
- `dashboard/src/index.css` — append three `@keyframes` (one per layer with phase offset) and a `@media (prefers-reduced-motion: reduce)` block that sets `animation: none` on the layer class.
- `dashboard/ui-contract/transcription-suite-ui.contract.yaml` — amend `AudioVisualizer.behavior_rules.raf-loop` text to acknowledge dual paths (rAF when active, declarative CSS keyframes when idle); add `idle-svg` to `AudioVisualizer.allowed_variants.mode`. Run the full extract → build → validate --update-baseline → check pipeline.
- `dashboard/components/__tests__/AudioVisualizer.test.tsx` (NEW) — render gating tests: SVG branch present when `!isActive && !analyserNode`, absent when `analyserNode` provided, absent when `isActive=true`. Use jsdom DOM queries; do not assert on animation timing (jsdom does not run CSS animations).

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/AudioVisualizer.tsx` — added the idle SVG branch with three `<path>` elements (`idle-wave-cyan`, `idle-wave-magenta`, `idle-wave-orange`), `viewBox="0 0 800 200"`, `preserveAspectRatio="none"`, `vectorEffect="non-scaling-stroke"` so stroke width stays 2px regardless of container aspect ratio. Branch reuses the same outer wrapper (`<div>` with grid overlay) — `<canvas>` only renders when not idle. `data-testid="audio-visualizer-idle-svg"` for testing. `aria-hidden="true"` since the visualizer is decorative.
- [x] `dashboard/src/index.css` — appended three `@keyframes` (`idle-wave-cyan` 4s, `idle-wave-magenta` 4s with `-1.3s` delay, `idle-wave-orange` 5s with `-2.7s` delay), three class rules with `transform-box: fill-box; transform-origin: center`, and a `@media (prefers-reduced-motion: reduce)` block that suppresses motion. Each keyframe combines `translateY` (compositor-cheap) and a small `scaleY` to recreate the legacy `Math.sin(t*0.5)` envelope swell.
- [x] `dashboard/scripts/ui-contract/build-contract.mjs` — broadened `AudioVisualizer.behavior_rules.raf-loop` rule wording to acknowledge the dual rendering paths; added `idle-svg` to `allowed_variants.mode`; broadened `structural_invariants.canvas-layering` and `state_rules.responsive-resize` rules so they describe the canvas + SVG dual-mode invariant. (The YAML is generated; the source-of-truth is this `.mjs` file.)
- [x] `dashboard/ui-contract/transcription-suite-ui.contract.yaml` — bumped `meta.spec_version` from 1.0.21 to 1.0.22 (manual step per the build script's preserve-version semantics); regenerated via `npm run ui:contract:build`; baseline updated via `node scripts/ui-contract/validate-contract.mjs --update-baseline`.
- [x] `dashboard/components/__tests__/AudioVisualizer.test.tsx` (NEW, 3 tests) — covers the I/O matrix render-gating cases (true idle → SVG with all 3 paths and pinned palette colors / no canvas, with analyser → no SVG / canvas mounted, active → no SVG / canvas mounted).

**Acceptance Criteria:**
- Given a fresh `AudioVisualizer` mount with no analyser and `isActive=false`, when the user opens the dashboard, then three colored animated waves are visible inside the visualizer container within ~100ms of mount (no flash of blank).
- Given an `AudioVisualizer` mounted with an `AnalyserNode` but `isActive=false` (paused recording or pre-playback audio note), when the user observes the visualizer, then the container stays blank — no SVG, no canvas paint.
- Given an `AudioVisualizer` with `isActive=true`, when the user observes the visualizer, then the existing canvas/rAF branch behaves identically to today (no visual or perf regression).
- Given the OS `prefers-reduced-motion: reduce` setting is enabled, when the idle branch renders, then the three SVG paths are visible but do not animate (static character preserved).
- Given `cd dashboard && npm run typecheck`, then it passes.
- Given `cd dashboard && npm run ui:contract:check`, then it passes (after the baseline regeneration in the contract task).
- Given `cd dashboard && npm test -- AudioVisualizer`, then the new test file passes.

## Spec Change Log

### 2026-04-26 — review-iteration 1: patches only (no spec amendment)

**Findings (2 reviewers, 9 distinct findings after dedup):**
- 1 PATCH — both reviewers flagged that `AudioVisualizer.test.tsx` tests 2 and 3 used `document.querySelector('canvas')` instead of scoping the query to the render container. Today this is safe because `afterEach(cleanup)` unmounts each test's tree, but it is a `@testing-library/react` anti-pattern. **Fixed in code** by destructuring `{ container }` from `render()` and using `container.querySelector('canvas')`.
- 0 BAD_SPEC, 0 INTENT_GAP — frozen block remains correct, no loopback required.
- 4 REJECT — TS reviewer's "HIGH stale closure" misreads React's `useEffect` cleanup-closure semantics (each cleanup paired with its own `animationId`); CSS `animation-delay` split-from-shorthand is stylistic; `transform-box: fill-box` and `vectorEffect="non-scaling-stroke"` browser-version concerns don't apply to Electron 40 / Chromium 134; `idle-wave-*` class collision risk confirmed nil.
- 1 REJECT (would be DEFER but disqualified by triage) — `amplitudeScale` shadow variable at `AudioVisualizer.tsx:80` (`const amplitudeScale = height / 200` shadows the outer prop). Pre-existing bug from the legacy `drawSimulation()`, predates even gate-87. Per `deferred-work.md` triage rule criterion 2 ("not pre-existing"), this does not qualify for the deferred-work shelf.

**KEEP (must survive any future re-derivation):** the `!isActive && !analyserNode` SVG-branch gate (preserves the gate-87 perf win for the paused-with-analyser state); the `transform`/`opacity`/`scaleY`-only animation properties (compositor-thread); and the `prefers-reduced-motion` no-animation block (visual character preserved without motion).

## Design Notes

**Why SVG paths, not animated CSS gradients:** A pure-CSS approach (e.g. animated `linear-gradient` mask) cannot reproduce the layered sine-wave silhouette without either bitmap masks (introduces an asset) or many absolutely-positioned `<div>` slices (defeats the "compositor-only" goal). Three `<path>` elements with phase-offset translate keyframes give the same visual effect with minimum DOM weight (3 elements vs. dozens) and use only transform/opacity — the cheapest properties for the compositor.

**Why animate `transform`/`opacity` only:** These are the two properties browsers can animate purely on the compositor thread without invoking layout or paint. Animating `d`, `stroke-dashoffset`, `width`, or `top` would force a paint each frame on the SVG layer — which is exactly the kind of cost the gate-87 work exists to remove. Translate-based phase shift on a static path silhouette gives "wave motion" perception without per-frame paint.

**Why `viewBox` resize, not JS:** SVG with `viewBox="0 0 800 200"` and `preserveAspectRatio="none"` scales to whatever its parent's CSS dimensions are, and the browser handles re-rasterization on resize. No `window.addEventListener('resize', ...)` is needed — and crucially, no JS code runs at all during idle, satisfying the gate-87 invariant.

## Verification

**Commands:**
- `cd dashboard && npm run typecheck` — expected: passes; no new TS errors.
- `cd dashboard && npm test -- AudioVisualizer` — expected: new test file's three render-gating tests pass.
- `cd dashboard && npm run ui:contract:extract && npm run ui:contract:build && node scripts/ui-contract/validate-contract.mjs --update-baseline && npm run ui:contract:check` — expected: full pipeline passes; new baseline reflects the broadened behavior_rule wording and the new `idle-svg` variant.

**Manual checks:**
- Open the dashboard with no recording in progress; the visualizer container shows three slowly weaving cyan/magenta/orange waves (matching the legacy idle character).
- Start a recording — the SVG disappears, the existing canvas/rAF visualization takes over, and stops cleanly when the recording ends. The transition is invisible to the user (same outer container, just inner content swap).
- macOS / OS-level "Reduce motion" enabled: the visualizer still shows the three waves but they do not animate.
