---
title: 'GH-87 — Gate AudioVisualizer rAF on isActive prop'
type: 'bugfix'
created: '2026-04-20'
status: 'done'
baseline_commit: '05899af'
context:
  - '{project-root}/_bmad-output/brainstorming/brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `AudioVisualizer.tsx` schedules `requestAnimationFrame(draw)` unconditionally for the lifetime of the component, so the sine-wave `drawSimulation` (3 layered `Math.sin` passes per pixel + Retina canvas paint) and the `drawReal` path both run at the display refresh rate (60 Hz on most platforms; 120 Hz on M-series ProMotion) regardless of whether any audio is actually flowing or the visualizer is even visible. This is the #1 ranked root cause from the issue-87 RCA brainstorm (estimated 40–60 % of the reported idle CPU/GPU on Mac), amplified multiplicatively because the canvas is mounted inside a `backdrop-blur-xl` `GlassCard` whose blur region must be re-sampled on every canvas tick.

**Approach:** Add an `isActive: boolean` prop to `AudioVisualizer` that defaults to `false`. When `false`, the effect runs `resize()` once (so the canvas is sized correctly when later activated) and exits without scheduling any rAF; when `true`, the existing rAF loop runs as today. Update all three call sites to opt in only when their owning UI is genuinely live: SessionView when an analyser is attached, FullscreenVisualizer when the overlay is fully visible, AudioNoteModal when audio is playing. No visual change while active; while inactive the canvas stays at its last frame (typically blank), matching the "Idle — awaiting input" / "No Input" textual states the surrounding UI already shows.

## Boundaries & Constraints

**Always:**
- `isActive` defaults to `false` so future call sites that omit it cannot accidentally re-introduce the always-on loop.
- The `useEffect` dependency array includes `isActive` so toggling it re-runs the effect cleanly.
- `cancelAnimationFrame` is still called on cleanup whenever a frame was scheduled.
- A single `resize()` runs on mount (and on `resize` events) regardless of `isActive`, so the canvas is correctly sized the moment it activates — no first-frame flash of stretched/blurry content.
- All three existing call sites are updated in the same patch; build must stay green.
- UI contract entry for `AudioVisualizer` (`dashboard/ui-contract/transcription-suite-ui.contract.yaml`) is left structurally intact — no token additions required for a behavior-only change. Run `npm run ui:contract:check` after edits to confirm no drift.

**Ask First:**
- If activating `isActive` mid-life turns out to need a frame-zero reset of the simulation phase counter `t` (so the wave doesn't visibly resume mid-cycle), surface it before adding a `useRef`/reset.

**Never:**
- Do not change the canvas DOM, the `drawReal`/`drawSimulation` rendering math, or the `analyserNode`/`amplitudeScale` props.
- Do not fix the per-frame `new Uint8Array(analyserNode.fftSize)` allocation in `drawReal` (B11/I76) — out of scope; tracked separately.
- Do not touch any other rAF/timer site flagged in the brainstorm (UpdateBanner timer, useWordHighlighter, SessionView scroll rAF, ModelManagerTab churn).
- Do not introduce IntersectionObserver/visibility-based auto-gating in this patch — keep the gate explicit and caller-controlled.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mounted with `isActive=false` (default) | No prop passed; analyserNode may or may not be present | `resize()` runs once; canvas sized; **no `requestAnimationFrame` scheduled**; no `draw*` calls | N/A |
| Mounted with `isActive=true`, no analyser | `isActive={true}`, `analyserNode={null}` | `drawSimulation` runs every frame as today | N/A |
| Mounted with `isActive=true`, analyser flowing | `isActive={true}`, `analyserNode={AnalyserNode}` | `drawReal` runs every frame as today | N/A |
| Toggle `isActive` false → true after mount | Parent flips prop | Effect re-runs; rAF loop starts; canvas animates | N/A |
| Toggle `isActive` true → false after mount | Parent flips prop | Effect cleanup runs; `cancelAnimationFrame` called; loop stops; canvas freezes on last frame | N/A |
| Unmount while active | Component removed | `cancelAnimationFrame` called as today; resize listener removed | N/A |
| `analyserNode` reference changes while active | Parent swaps analyser | Effect re-runs (already in deps); new rAF loop with new analyser | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/components/AudioVisualizer.tsx` -- component being gated; add `isActive` prop, branch effect on it, include in deps
- `dashboard/components/views/SessionView.tsx` -- call site at line ~1875; pass `isActive={!!activeAnalyser}` (the existing `activeAnalyser` is `null` when no audio is flowing — perfect signal)
- `dashboard/components/views/FullscreenVisualizer.tsx` -- call site at line 105; pass `isActive={isRendered && !!analyserNode}` (animate while the portal is mounted — i.e. through the entire 500 ms fade-out — and only when there is real audio to draw; gating on `isVisible` would freeze the canvas the instant the user clicks close, producing a visible stutter through the exit animation)
- `dashboard/components/views/AudioNoteModal.tsx` -- call site at line 1498; pass `isActive={isPlaying && !!analyserNode}` (decorative visualizer behind playback controls — only animate while playback is running AND the Web Audio analyser has been wired up by `handleLoadedMetadata`; without the analyser guard, hitting Play before metadata loads would show the synthetic sine-wave simulation overlay for one or two frames)
- `dashboard/components/__tests__/SessionView.test.tsx` -- mocks `AudioVisualizer` to a stub div; no change required, but verify mock survives the new prop signature
- `dashboard/ui-contract/transcription-suite-ui.contract.yaml` -- entry exists; behavior-only change should not affect tokens

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/components/AudioVisualizer.tsx` -- add `isActive?: boolean` to `AudioVisualizerProps` (default `false`); inside `useEffect`, run `resize()` and attach the resize listener as today, then `if (!isActive) return cleanup` BEFORE `draw()` is invoked; add `isActive` to the dependency array. Cleanup must still remove the resize listener and (when scheduled) call `cancelAnimationFrame`.
- [x] `dashboard/components/views/SessionView.tsx` -- on the `<AudioVisualizer>` at line ~1875 add `isActive={!!activeAnalyser}`.
- [x] `dashboard/components/views/FullscreenVisualizer.tsx` -- on the `<AudioVisualizer>` at line 105 add `isActive={isRendered && !!analyserNode}`.
- [x] `dashboard/components/views/AudioNoteModal.tsx` -- on the `<AudioVisualizer>` at line 1498 add `isActive={isPlaying && !!analyserNode}`.
- [x] Run verification commands listed below.

**Acceptance Criteria:**
- Given the dashboard is open on the Session tab and no recording/analyser is active, when the user is idle, then no `draw` callback is scheduled by `AudioVisualizer` (verifiable by setting a `console.count` breakpoint inside `draw` during a manual check, or by Chromium DevTools Performance recording showing zero canvas paints from the visualizer region).
- Given the user starts recording (so `activeAnalyser` becomes non-null), when audio begins flowing, then the visualizer animates as it does today with no perceptible delay or first-frame layout shift.
- Given the user opens FullscreenVisualizer **with live input**, when the overlay mounts, then the visualizer begins animating as soon as the canvas has a non-zero width (no waiting for the fade-in transition to complete) and **continues animating throughout the 500 ms fade-out** until the portal unmounts.
- Given the user opens FullscreenVisualizer **without live input** (`analyserNode` is null), when the overlay is showing, then the visualizer never animates (no synthetic sine-wave simulation in the fullscreen view).
- Given AudioNoteModal is open and audio is paused, when the modal is idle, then the decorative background visualizer is not animating; pressing Play **after** metadata loads resumes animation; pressing Pause stops it; pressing Play **before** metadata loads (race window) does NOT show the synthetic sine-wave simulation.
- `npm run lint`, `npm run typecheck`, and `npm run test` (frontend) all pass.
- `npm run ui:contract:check` reports no drift.

## Spec Change Log

### 2026-04-21 — Iteration 2 (post-step-04 review loop)

**Findings triggering amendment:**

1. **Edge-Hunter HIGH #1** — `FullscreenVisualizer.tsx:108` originally specified `isActive={isVisible}`. The `isVisible` flag flips false the instant the user clicks close, but the portal stays mounted for the full 500 ms fade-out (`FullscreenVisualizer.tsx:33-35`). The visualizer would therefore freeze on its last frame for the entire exit animation — visible stutter against the fading-out backdrop blur, exactly the kind of "feels broken" stall the spec is trying to eliminate elsewhere.

2. **Edge-Hunter MEDIUM #3** — `AudioNoteModal.tsx:1498` originally specified `isActive={isPlaying}`. `analyserNode` is created lazily inside `handleLoadedMetadata` (`AudioNoteModal.tsx:936-959`), so a user who hits Play before metadata loads (cached blobs, autoplay-on-mount) opens a brief race window where `isPlaying=true && analyserNode=null`, which sends `AudioVisualizer` into the `drawSimulation` branch. The decorative overlay would briefly show synthetic sine waves unrelated to the audio.

**Amendment applied (non-frozen sections only — Code Map, Tasks, Acceptance Criteria):**

- FullscreenVisualizer call site changed to `isActive={isRendered && !!analyserNode}`. Animation now runs while the portal is mounted (covering the entire fade-in *and* fade-out windows) and only when there is real audio. No simulation in the fullscreen view ever — that view is for analytical display of live input only.
- AudioNoteModal call site changed to `isActive={isPlaying && !!analyserNode}`. The `&& !!analyserNode` clause closes the metadata-load race; without it, the overlay flashes synthetic waves on early Play.
- Acceptance Criteria for the FullscreenVisualizer scenario rewritten to require animation through fade-out and to add a "no simulation when no input" criterion.
- Acceptance Criteria for the AudioNoteModal scenario expanded with the explicit pre-metadata Play race condition.

**Known-bad states avoided:**

- 500 ms frozen-canvas stutter through the FullscreenVisualizer exit transition.
- Brief synthetic sine-wave overlay on AudioNoteModal Play before metadata loads.

**KEEP instructions (must survive re-derivation):**

- Default `isActive=false` on the prop — the safety floor that prevents future call sites from accidentally re-introducing the always-on loop. **Do not change.**
- The `cleanup` closure pattern in `AudioVisualizer.tsx` (declare cleanup, then `if (!isActive) return cleanup` before `draw()`). The order — `resize()` → listener → cleanup decl → gate → draw — is load-bearing. **Do not reorder.**
- `isActive` in the effect's dependency array. **Do not remove.**
- The SessionView call site `isActive={!!activeAnalyser}`. Verified during review that `setAnalyser(null)` is called from 12+ sites in `useLiveMode.ts` and `useTranscription.ts` whenever recording stops/errors/teardown happens, so this gate reliably deactivates. **Do not change.**

**Findings rejected (recorded for trail):**

- Blind-Hunter MED #2 (SessionView analyser persistence) — verified false; `setAnalyser(null)` is comprehensive.
- Blind-Hunter LOW #1 / Edge-Hunter G (paused AudioNoteModal shows frozen bars) — intentional and arguably better UX than perpetually-moving synthetic waves behind a paused player.
- Blind-Hunter LOW #3 / Edge-Hunter H (`t=0` phase reset on toggle) — invisible in real flows since simulation only runs when no analyser is present.

**Findings deferred (none appended to deferred-work.md):**

- Edge-Hunter HIGH #2 (initial-mount width=0 paint) — pre-existing, fails triage rule #2.
- Edge-Hunter MEDIUM #4 (`amplitudeScale` dep tear-down on slider step) — pre-existing dependency, fails triage rule #2.
- Edge-Hunter MEDIUM #5 (stale `freqData` if `fftSize` changes) — pre-existing AND speculative (no call site swaps `fftSize`), fails rules #2 and #4.

## Design Notes

The single-line `if (!isActive) return cleanup` placement is deliberate: it must come **after** `resize()` and the resize-listener attachment but **before** `draw()`, so the canvas is correctly sized the instant the gate flips on. Without this, activating the visualizer on a freshly-mounted component would paint the first frame at 0×0 until the next window resize.

Returning `cleanup` (instead of `undefined`) from the early-exit branch ensures the resize listener is still removed on unmount of inactive components — important because parent components may mount AudioVisualizer eagerly and only flip `isActive` later.

Why default `false` rather than `true`: the brainstorm RCA is explicit (Drill 2.8, ranked action #1) — defaulting to opt-in means a future careless `<AudioVisualizer />` somewhere new cannot silently re-introduce the always-on loop. The cost of this safety is one extra prop at three call sites we already know.

Why not gate via IntersectionObserver / `document.visibilityState` instead: those automated approaches add complexity and can mis-fire for partially-occluded windows (exactly the macOS NSWindow occlusion bug noted in cluster D39). Explicit caller control matches the actual user-meaningful semantics ("is audio flowing?" / "is this modal showing?" / "is playback running?").

## Verification

**Commands:**
- `cd dashboard && npm run lint` -- expected: 0 errors
- `cd dashboard && npm run typecheck` -- expected: 0 type errors (new optional prop is backwards-compatible at the type level)
- `cd dashboard && npm test -- AudioVisualizer SessionView` -- expected: existing tests pass; SessionView mock for AudioVisualizer continues to work
- `cd dashboard && npm run ui:contract:check` -- expected: no drift

**Manual checks (if no CLI):**
- Launch dashboard dev build, open Session tab with no recording, open Chromium DevTools → Performance → record 5 s of idle. Confirm no recurring canvas paints attributable to `AudioVisualizer`.
- Start recording. Confirm visualizer animates immediately, with no visible 0×0 first frame or stretched canvas.
- Stop recording. Confirm visualizer freezes on its last frame within ~1 frame.
- Open FullscreenVisualizer with live input; confirm animation runs throughout fade-in *and* fade-out (no mid-fade freeze).
- Open FullscreenVisualizer with no live input; confirm the fullscreen view stays static (no synthetic sine waves).
- Open an AudioNote, press Play and Pause repeatedly; confirm the decorative background visualizer animates only while playing AND analyser is wired up (no synthetic-sim flash on quick Play before metadata loads).

## Suggested Review Order

**Component contract (the gate itself)**

- New `isActive` prop with safety-default `false` and the JSDoc explaining why.
  [`AudioVisualizer.tsx:9`](../../dashboard/components/AudioVisualizer.tsx#L9)

- Effect's early-exit gate — must come *after* `resize()` + listener attach, *before* `draw()`, returning the named `cleanup` so the resize listener is freed even when no rAF was ever scheduled.
  [`AudioVisualizer.tsx:50`](../../dashboard/components/AudioVisualizer.tsx#L50)

- Dependency array — `isActive` added so toggling re-runs the effect cleanly.
  [`AudioVisualizer.tsx:162`](../../dashboard/components/AudioVisualizer.tsx#L162)

**Call-site gate selection (where the perf win lands)**

- Session tab gate — `!!activeAnalyser` is the canonical "audio is flowing" signal; `setAnalyser(null)` is called from 12+ teardown paths in `useLiveMode.ts` / `useTranscription.ts`.
  [`SessionView.tsx:1878`](../../dashboard/components/views/SessionView.tsx#L1878)

- Fullscreen overlay gate — `isRendered && !!analyserNode` keeps animation through the full 500 ms fade-out and suppresses the synthetic simulation when no input.
  [`FullscreenVisualizer.tsx:106`](../../dashboard/components/views/FullscreenVisualizer.tsx#L106)

- Audio-note playback gate — `isPlaying && !!analyserNode` closes the metadata-load race window so paused/loading playback never flashes a synthetic waveform.
  [`AudioNoteModal.tsx:1498`](../../dashboard/components/views/AudioNoteModal.tsx#L1498)
