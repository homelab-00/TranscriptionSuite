---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: ['brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md']
session_topic: 'Restore the AudioVisualizer idle animation without re-introducing the cross-platform Electron/Chromium idle CPU/GPU cost that got it removed in 048dba8 (Issue #87)'
session_goals: 'Generate many distinct approaches for showing a pleasing idle visual on surfaces that embed AudioVisualizer, without running a 60-120 Hz rAF loop and without multiplicatively invalidating the backdrop-blur-xl re-sample of the wrapping GlassCard. Explore the user-suggested pre-recorded loop and orthogonal alternatives.'
selected_approach: 'ai-recommended'
techniques_used: ['Assumption Reversal', 'SCAMPER Method', 'Cross-Pollination', 'Solution Matrix']
ideas_generated: 106
technique_execution_complete: true
top_recommendations:
  - 'P4-19: Stillness-into-motion — no idle animation; the transition from idle to live IS the animation moment'
  - 'P4-10: Pure CSS pseudo-element outside GlassCard blur region — compositor-only ambient cue'
  - 'P4-4: 99%-static + 60s breath — 1.7% of continuous animation budget'
structural_unlock: '[AR5] — move motion outside the GlassCard backdrop-blur region; breaks the canvas-under-blur multiplier that makes video-on-canvas only a half-win'
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-04-21

## Session Overview

**Topic:** Restore the `AudioVisualizer` idle animation without re-introducing the cross-platform Electron/Chromium idle CPU/GPU cost that got it removed in commit 048dba8 (Issue #87).

**Goals:** Generate many distinct approaches for showing a pleasing idle visual on surfaces that embed `AudioVisualizer`, without running a 60-120 Hz rAF loop, and without the GlassCard compositing multiplier — then rank them.

### Context Guidance (carried from 2026-04-20 session)

- Commit 048dba8 gated `requestAnimationFrame` on `isActive`, silencing the canvas at 60-120 Hz when no audio is live. **Gains apply on every Electron/Chromium platform** (Linux, Windows, macOS) — Mac was just the *loudest amplifier* because of Retina DPI, ProMotion 120 Hz, Metal compositor, and NSWindow occlusion firing only on full cover.
- Multiplicative cost discovery: `AudioVisualizer` sits **inside a `<GlassCard>`** with `backdrop-blur-xl` (`SessionView.tsx:1875`, wrapped by `GlassCard.tsx:18`). Any per-frame repaint of the canvas invalidates the backdrop-blur region and forces Chromium to re-sample and re-blur under it every frame. **A "pre-recorded video played on the canvas" would have the same multiplier** unless we also break the canvas-under-blur coupling.
- Three call sites each have a distinct "live" signal: `SessionView` → `!!activeAnalyser`, `FullscreenVisualizer` → `isRendered && !!analyserNode`, `AudioNoteModal` → `isPlaying && !!analyserNode`. Idle happens only on `SessionView` (the other two already lazy-activate).

### Session Setup

User confirmed AI-recommended sequence: Assumption Reversal (foundation/reframe) → SCAMPER (divergent generation) → Cross-Pollination (push past obvious) → Solution Matrix (score & shortlist).

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** Restore the idle AudioVisualizer without re-introducing the cross-platform Electron idle cost. User has a starter idea (pre-record the animation loop) that needs to be validated or challenged.

**Recommended Techniques:**

- **Phase 1 — Assumption Reversal:** Surface every assumption baked into "restore the idle animation" and flip each one. Stress-tests the user's "recorded loop" starter idea and opens adjacent solution spaces.
- **Phase 2 — SCAMPER Method:** Systematically generate idea variants across 7 lenses (Substitute, Combine, Adapt, Modify, Put-to-other-uses, Eliminate, Reverse). Bulk of 50-70 idea count.
- **Phase 3 — Cross-Pollination:** Borrow approaches from iOS Now Playing, Spotify, Siri orb, Apple Watch, Discord voice dots, Winamp, etc., for cheap idle-presence tricks. Pushes past obvious answers into the "ideas 50-100" territory.
- **Phase 4 — Solution Matrix:** Score candidates on Idle CPU, Idle GPU, visual cohesion with glass design, implementation effort, cross-platform risk, and regression-guard feasibility. Ends with a ranked shortlist.

**AI Rationale:** The problem combines tight performance constraints with visual-design sensitivity — AR surfaces what must hold vs what can bend; SCAMPER generates broadly without letting us fixate on the canvas framing; Cross-Pollination inoculates against the "first 20 ideas are boring" failure mode; Solution Matrix converges without losing options.

---

## Phase 1: Assumption Reversal

**Goal:** Surface every assumption baked into "restore the idle animation," flip it, annotate whether the flip opens genuine design space. Tags: **KEEP** (real flip to pursue), **WATCH** (conditional — might matter later), **DROP** (flip doesn't open anything new).

### Axis 1 — What the visual is *for*

**[AR1]** *Assumption:* **"We need an idle animation at all."**
- *Flip:* We don't. The post-048dba8 state (silent canvas) is the default and might just be fine — nobody on Issue #87 complained about the removal.
- *Opens:* Do nothing. Ship zero. Test whether users even notice the absence over 2 weeks before investing.
- *Tag:* **KEEP** — null hypothesis every idea must beat.

**[AR2]** *Assumption:* **"The idle visual's job is decoration (delight)."**
- *Flip:* Its job is *feedback* ("the app is alive and hardware is wired up"). Or *affordance* ("this is where recording happens — click/speak here").
- *Opens:* If feedback → a static mic-ready glyph suffices. If affordance → the visual should pulse only on mouse-near or input-device-change events.
- *Tag:* **KEEP** — changes acceptance criterion for every Phase 2 candidate.

**[AR3]** *Assumption:* **"The idle visual must be pleasant and subtle."**
- *Flip:* It should be *dramatic* — a bigger, bolder, once-per-session cold-open that then fades to nothing.
- *Opens:* 3-second grand entrance, then stop. Idle cost: 3s × 60 Hz instead of infinite.
- *Tag:* **KEEP** — solves the cost problem by making the animation *finite*.

### Axis 2 — Where it lives (surface + layer)

**[AR4]** *Assumption:* **"The idle visual must be on the Session tab's visualizer region."**
- *Flip:* It lives elsewhere — the sidebar, the tray icon, the window border, the app header's glow.
- *Opens:* Tray-icon pulse, window-level border glow, sidebar-bottom ambient orb.
- *Tag:* **WATCH** — powerful but changes the design language beyond "visualizer."

**[AR5]** *Assumption:* **"The animation lives inside the `<GlassCard>`."**
- *Flip:* Outside the GlassCard — sibling element, CSS pseudo-element on the card's border, or transparent div layered *above* the card.
- *Opens:* Breaks the canvas-under-blur multiplier entirely. Any motion that doesn't pass through the blur region is free from re-sample cost.
- *Tag:* **KEEP** — the structural unlock; almost every Phase 2 idea can use it.

**[AR6]** *Assumption:* **"The visualizer has one canvas."**
- *Flip:* Two surfaces — one outside the blur region for idle animation, one inside (static) for the live waveform.
- *Opens:* Idle=outside-blur motion; live=inside-blur canvas.
- *Tag:* **KEEP** — natural implementation pattern when audio is live.

**[AR7]** *Assumption:* **"The GlassCard covers the whole visualizer region."**
- *Flip:* The GlassCard uses clip-path/mask to carve a hole where the visualizer sits. Motion under the hole doesn't re-sample blur.
- *Opens:* Same perf effect as [AR5] but keeps the visualizer inside the card aesthetically.
- *Tag:* **WATCH** — implementation risk (clip-path on backdrop-filter has cross-platform quirks).

### Axis 3 — How it moves (engine + framerate)

**[AR8]** *Assumption:* **"The animation must be generated procedurally (JS sin waves)."**
- *Flip:* Pre-baked asset — video, WebP, animated GIF, Lottie JSON, SVG animation, CSS keyframes.
- *Opens:* The user's starter idea. 5+ concrete asset formats to compare in Phase 4.
- *Tag:* **KEEP** — user's starter idea, deserves thorough Phase 2 expansion.

**[AR9]** *Assumption:* **"The animation must run at the display's refresh rate (60-120 Hz)."**
- *Flip:* 10 Hz. Or 2 Hz. Or 1 Hz.
- *Opens:* `setInterval` at 6-10 Hz feels slow-breathing, not smooth — 6-12× cheaper, might be more aesthetic (iPod-nano era).
- *Tag:* **KEEP** — "slowed-down" is an aesthetic category, not just a perf compromise.

**[AR10]** *Assumption:* **"The animation must be driven by JS."**
- *Flip:* Pure CSS keyframes + `transform` / `opacity` / `filter: hue-rotate`. Compositor-only, zero JS ticks.
- *Opens:* CSS animations run on the compositor without JS; but under a blur layer they *still* cost blur re-sample unless combined with [AR5].
- *Tag:* **KEEP** — classic cheap option; requires co-placement decisions.

**[AR11]** *Assumption:* **"The animation must be continuous."**
- *Flip:* Interaction-triggered — on mouse hover, focus, mouse-within-200px, or on a specific event (new model loaded, connection state changed).
- *Opens:* Hover-to-animate = discoverable affordance. Mouse-proximity = Apple-style delight.
- *Tag:* **KEEP** — pairs beautifully with [AR2] "affordance" framing.

**[AR12]** *Assumption:* **"The animation plays forever while mounted."**
- *Flip:* Plays once (or N times) and stops. Component tracks "been seen this session."
- *Opens:* Same budget as [AR3] — finite animation.
- *Tag:* **KEEP** — subtle variant of [AR3].

### Axis 4 — What it looks like

**[AR13]** *Assumption:* **"It must look like a waveform (sine/bars)."**
- *Flip:* Something else — ambient orb, particle cloud, Siri-style ribbon, breathing dot, shimmer across a gradient, slowly-rotating mesh gradient, 3-LED constellation, typewriter "listening..." text.
- *Opens:* Decouples idle visual from audio-data-driven visual. Big design-space unlock.
- *Tag:* **KEEP**.

**[AR14]** *Assumption:* **"Idle and live must look visually related."**
- *Flip:* Two completely different visuals. Idle = static mic icon with pulse; live = waveform. Transition = cross-fade.
- *Opens:* User instantly knows which state (affordance++). Static-icon idle = zero cost.
- *Tag:* **KEEP** — pairs with [AR2].

**[AR15]** *Assumption:* **"The visual must be colorful (cyan/magenta/orange)."**
- *Flip:* Idle is monochrome / desaturated — color blooms in when audio goes live.
- *Opens:* "Saturation swell" on speech start is an effect; idle's monochrome is cheaper.
- *Tag:* **WATCH** — aesthetic, not a perf driver on its own.

### Axis 5 — How it's implemented

**[AR16]** *Assumption:* **"The animation must be client-side code."**
- *Flip:* Baked into the build at build time (pre-recorded video/WebP/Lottie); client just plays it.
- *Opens:* Build-time generator script. Render the sine-wave sim once into a Lottie JSON or WebP; ship as asset; swap canvas for `<img>` or Lottie player.
- *Tag:* **KEEP** — concrete execution path for [AR8].

**[AR17]** *Assumption:* **"We can only use Web APIs."**
- *Flip:* Native mode — NSVisualEffectView on Mac, OffscreenCanvas in WebWorker, Electron native titlebar.
- *Opens:* Exotic, probably too much complexity. Documented as upper bound.
- *Tag:* **DROP** — scope blowout vs return.

**[AR18]** *Assumption:* **"Sim and real-audio share the same component."**
- *Flip:* Two components. `IdleVisualizer` (tiny, cheap) and `LiveAudioVisualizer` (canvas, rAF, real data). Parent picks based on `isActive`.
- *Opens:* Clean separation, testable in isolation; IdleVisualizer can be a static SVG or Lottie.
- *Tag:* **KEEP** — implementation pattern many Phase 2 ideas will assume.

**[AR19]** *Assumption:* **"The existing `drawSimulation()` is the baseline to match."**
- *Flip:* The baseline is something *better* — drawSimulation was mediocre (predictable lissajous, blows out at low heights). A new idle visual can be a design upgrade, not just perf-neutral restoration.
- *Opens:* Reframes acceptance criterion from "restore" to "replace with something nicer AND cheaper."
- *Tag:* **KEEP**.

**[AR20]** *Assumption:* **"The change should be local to `AudioVisualizer.tsx`."**
- *Flip:* The change can touch SessionView, GlassCard, or introduce a new component (`IdleAmbient`). Broader scope is fine if payoff is better.
- *Opens:* Gives permission to restructure the DOM around the card — required by [AR5], [AR6], [AR7].
- *Tag:* **KEEP** — permission-granting flip.

### Phase 1 Tally

- **20 assumptions listed** across 5 axes.
- **14 tagged KEEP**, 3 WATCH, 1 DROP, 2 reframings (null hypothesis, design upgrade).
- **Biggest structural unlock:** [AR5] — move motion *outside* the GlassCard's blur region.
- **Most playful unlock:** [AR3]/[AR12] — make the animation **finite**.
- **Most humbling unlock:** [AR1] — the null hypothesis, "do nothing."
- **User's starter idea ([AR8]):** valid, deserves Phase 2 expansion into ~5 concrete formats.

---

## Phase 2: SCAMPER Method

**Goal:** Generate 50-70 candidate ideas across 7 SCAMPER lenses, using the KEEP flips from Phase 1 as permission-space. Idea format: **[S#]** Title — concept (one line) — novelty tag.

### S — Substitute (what to replace the procedural canvas with?)

**[S1]** *Lottie JSON + lottie-web player.* Export a 6-second loop of the sine wave from AfterEffects/LottieFiles, play via lottie-web. *Novelty:* Lottie renders SVG paths, runs at 60fps but with heavy CSS-transform optimizations; works on any element, including outside the blur region.

**[S2]** *Pre-baked WebP animation.* Use ffmpeg to render the existing `drawSimulation()` to a 3-second animated WebP (10 fps, 200 KB). Use as `<img src=...>`.  *Novelty:* Decoded once, frames replayed by browser; under Chromium, animated WebP is decoded on a worker thread and uploaded as static textures — cheaper than canvas paint.

**[S3]** *Muted autoplay `<video>` tag.* Record `drawSimulation()` to a 5-second H.264 MP4 at 24fps, 300 KB. Play as a muted, looped, autoplaying `<video>`. *Novelty:* Hardware-accelerated video decode on all 3 platforms; Chromium treats `<video>` as a composited layer, no re-paint of parent.

**[S4]** *SVG with `<animate>` elements.* Static SVG path, animate dasharray/offset declaratively. *Novelty:* SMIL animation on SVG runs in the compositor; widely supported but quirky on some Safari builds (not an issue for Electron/Chromium).

**[S5]** *CSS keyframes on a pseudo-element.* A `::before` on the card border draws a gradient, animates via `transform: translateX`. *Novelty:* No JS, no canvas, no asset — but inherently limited to simple geometric motion.

**[S6]** *WebGL shader.* A 50-line fragment shader runs once per draw, but each draw can be triggered at 10Hz (not 60Hz). *Novelty:* GPU-resident, no rAF loop on CPU; but shader compilation is a cold-start cost and re-introduces the canvas-under-blur issue.

**[S7]** *A spritesheet of 20 static frames.* Use CSS `animation-timing-function: steps(20)` to step through a 20-frame sprite. *Novelty:* Single `<img>` load, pure CSS animation, no decoding per frame.

**[S8]** *Static SVG with a CSS mask-image shimmer.* A static gradient SVG, with a narrow "shimmer" gradient animated across it via `background-position`. *Novelty:* Shopify/Stripe-style skeleton shimmer; mature, zero-surprise perf.

**[S9]** *Canvas, but rendered once and paused.* Pre-paint a single beautiful static frame using the existing sine math, never schedule a second rAF. *Novelty:* No animation, but keeps the existing code path 95% intact — minimal diff.

**[S10]** *Unicode block-character "text" visualizer.* Render `▁▂▃▄▅▆▇▆▅▄▃▂▁` in monospaced font, CSS-animate the content (or rotate a set of strings on 1-second interval). *Novelty:* Retro ASCII aesthetic; entirely text-layer, no paint surface.

### C — Combine (mix approaches)

**[C11]** *Static SVG idle + canvas on live.* Mount `<IdleVisualizer>` (SVG, [AR18]) until `isActive`, then swap to canvas. *Novelty:* Clean state machine.

**[C12]** *Lottie idle + canvas on live, cross-fade on transition.* 300 ms opacity cross-fade between the two surfaces. *Novelty:* User perceives the state change viscerally; idle surface unmounts (zero cost) while live runs.

**[C13]** *Static gradient bg + animated border ring.* GlassCard border has a traveling light (CSS keyframes on `border-image`), while interior is static. *Novelty:* Activity signal on the border, which is outside the main blur region.

**[C14]** *CSS shimmer + a once-per-minute "breathe" pulse.* 99% of the time, static. Every 60 seconds, a 1-second opacity breath (0.7 → 1.0 → 0.7). *Novelty:* Breath-rate feedback; 59.5 of every 60s is zero cost.

**[C15]** *Static canvas frame + CSS `filter: hue-rotate` animating slowly.* Canvas is painted once (never re-painted), color animates via compositor filter. *Novelty:* The canvas never re-invalidates; the compositor-level hue-rotate is essentially free under Chromium.

**[C16]** *Pre-baked WebP loop + hover-triggered jog-wheel scrub.* Idle loop plays at 0.25× speed; hover accelerates to 1×. *Novelty:* Adds interactivity; mouse-over → animation responds without JS tick.

### A — Adapt (borrow from elsewhere — light; Cross-Pollination is Phase 3)

**[A17]** *Apple "Siri orb" shape.* Small pulsing orb instead of a waveform; adapts the most recognizable idle-listening cue. *Novelty:* High brand familiarity.

**[A18]** *macOS "Dictation" feedback.* Three dots that pulse sequentially. *Novelty:* System-level pattern, universally understood.

**[A19]** *Loading spinner discourse → "listening spinner" discourse.* Brand the idle state as "listening," use a listening-themed spinner. *Novelty:* Recontextualizes a familiar shape.

**[A20]** *YouTube's "listening to clips" bars.* Three vertical bars of varying height, animating step-wise (not continuous). *Novelty:* Familiar pattern from every music app.

**[A21]** *Spotify's wavy equalizer.* Subtle 3-bar equalizer glyph even when nothing's playing. *Novelty:* Well-known affordance for "audio surface."

### M — Modify (tweak dimensions of existing)

**[M22]** *Reduce framerate to 10 Hz via `setTimeout(draw, 100)`.* Keeps canvas path; 6× cheaper; looks like a deliberate "slow waveform" aesthetic. *Novelty:* Minimal code change.

**[M23]** *Reduce vertical range (make waves smaller/tighter).* Blur re-sample cost scales with invalidated area; a 20px-tall visualizer costs less than a 80px one. *Novelty:* Design tweak w/ measurable perf impact.

**[M24]** *Lower resolution canvas (ignore DPR).* Canvas backing store at 1× instead of 2× on Retina → 4× less texture to blur. *Novelty:* Accept some fuzziness in idle state.

**[M25]** *Fade opacity to 0.3 during idle.* Visual weight down; compositor still composites but user expects subtlety. *Novelty:* Perceptual trick.

**[M26]** *Smaller canvas (shrink to 30px tall strip during idle).* Animation area reduced; blur re-sample region reduced proportionally. *Novelty:* Idle = pencil-stroke-sized hint; live = full-size visualizer.

**[M27]** *Step motion instead of smooth.* Math.floor(x / 40) * 40 instead of continuous x. Quantized motion = fewer visually distinct frames = can drop to 2 fps without looking bad. *Novelty:* 8-bit aesthetic.

**[M28]** *Single waveform layer instead of 3.* Current drawSimulation has 3 nested sine layers × 3 strokes. Reduce to 1 layer → 3× cheaper. *Novelty:* Design simplification.

### P — Put to other uses (what else can the idle visualizer be?)

**[P29]** *Double as a loading spinner when models are downloading.* Use the same surface to show model-download progress (bar fills left-to-right). *Novelty:* One visual serves two jobs; always-useful feedback.

**[P30]** *Double as a connection-status indicator.* Red pulse when WebSocket down, green when connected, no motion when fully idle. *Novelty:* Replaces the separate "connection status" UI with motion cues on the visualizer surface.

**[P31]** *Double as the "ready to record" button itself.* Click the visualizer to start recording. Idle = "click me" affordance (subtle hover). *Novelty:* Collapses two elements into one.

**[P32]** *Use as a "transcription just finished" celebration.* Quick 2-second confetti burst on transcription complete, then back to idle. *Novelty:* Feedback moments instead of constant motion.

**[P33]** *Use as a level meter for input gain (not real-time audio).* Gain slider shows its value on the visualizer while being adjusted. *Novelty:* Reuses surface for UI affordance.

### E — Eliminate (remove things)

**[E34]** *Eliminate the visualizer entirely on idle.* Replace with a single centered "mic-ready" icon. [AR1] realized. *Novelty:* Simplest possible; zero cost baseline.

**[E35]** *Eliminate the GlassCard around the visualizer.* Flat background → no blur cost regardless of canvas activity. *Novelty:* Touches design language but radically simplifies.

**[E36]** *Eliminate the sine simulation; keep only drawReal.* When `analyserNode` is null, render nothing (canvas is blank). *Novelty:* Matches current post-048dba8 reality.

**[E37]** *Eliminate the canvas backing; use only DOM.* Replace with a `<div>` that has CSS-animated children. *Novelty:* DOM-only visualizer; subject to the same blur issue, but no 2D context.

**[E38]** *Eliminate the "animated" aesthetic from the design.* Rebrand as a "static dashboard" — no motion anywhere in idle. *Novelty:* Philosophical pivot.

**[E39]** *Eliminate the dedicated visualizer space; merge with other Session UI.* Use the existing "Live — listening / Idle — awaiting input" text as the sole idle indicator. *Novelty:* Already present (SessionView.tsx:1841); text-only affordance.

### R — Reverse / Rearrange (flip or re-order)

**[R40]** *Reverse: the canvas is empty by default; lights up on hover.* Idle = blank; hover = live-like preview animation. *Novelty:* Inverts the current default; extreme minimalism.

**[R41]** *Reverse: animation runs when the app is BACKGROUND, stops when FOREGROUND.* Cosmetic ambiance while user is in another app (Chromium throttles offscreen, so it'd be free anyway). *Novelty:* Absurd but educational — forces us to notice that idle-when-foreground is the expensive case.

**[R42]** *Reverse: animation plays on transition OUT of recording, not during idle.* "Goodbye wave" after a session ends; then quiet. *Novelty:* Animation as event marker, not ambient state.

**[R43]** *Rearrange: visualizer moves to the Sidebar when idle, back to SessionView when recording.* Idle = tiny sidebar orb; active = full SessionView visualizer. *Novelty:* Position-based state indicator.

**[R44]** *Rearrange: stack the idle visual on top of the live visual (z-index).* Live canvas = bottom layer, always rendered; idle = top layer, opacity 1 when idle, 0 when live. Only top layer animates. *Novelty:* No swap, just opacity.

**[R45]** *Reverse: let the visualizer be a passive mirror of window state (resizing, focus).* Window resizes → visualizer pulses. Window focuses → visualizer brightens once. No continuous animation. *Novelty:* Physical-state-driven animation; event-based.

**[R46]** *Reverse: instead of showing motion, show stillness that becomes motion.* A single vertical line, static, that starts wiggling the instant audio is detected. *Novelty:* The transition IS the animation.

### Phase 2 Tally

- **46 ideas** (S:10, C:6, A:5, M:7, P:5, E:6, R:7).
- **Cross-referencing to Phase 1 flips:**
  - [AR5]/[AR6] (motion outside blur): S3, S4, S5, S7, S8, C13, C14, R43
  - [AR8] (pre-baked asset): S1, S2, S3, S7, C12, C16
  - [AR10] (pure CSS): S5, S7, S8, C13, C14, C15, M27
  - [AR13] (non-waveform): A17, A18, A19, A20, A21, E34, C14, P32
  - [AR11] (interaction-triggered): C16, P31, R40
  - [AR3]/[AR12] (finite): C14, E34, P32, R42, R46
- **Standout ideas (subjective):**
  - **[S3] muted `<video>`** — likely closest to user's starter idea, with concrete perf advantage (HW video decode, compositor layer, no JS loop). Still has blur-re-sample unless combined with [AR5]/[AR7].
  - **[C15] static canvas + CSS `hue-rotate`** — painter's trick, preserves the aesthetic of the sine wave without re-painting.
  - **[C14] 99%-static + 1-sec breath every 60 sec** — tiny budget, maximum "app is alive" signal.
  - **[R46] stillness that becomes motion** — elegant, the transition itself is the animation.
  - **[P31] visualizer *is* the record button** — collapses two UI concerns.

---

## Phase 3: Cross-Pollination

**Goal:** Borrow idle-presence tricks from other apps/domains. Force ourselves into orthogonal territory — music apps, OS-level affordances, ambient computing, games, hardware indicators, print design, architecture. Target: 30-40 more ideas with a strong "surprise" emphasis. Idea format: **[X#]** Source → Idea — novelty tag.

### Domain 1 — iOS / Apple ecosystem

**[X1]** *iOS Lock Screen "Now Playing" sine wave.* Pre-rendered MP4 (Apple literally ships one — their wave is a video asset, not a live render). → Ship a 4-second loop as `<video>` that plays inside a CSS-masked region outside the blur. *Novelty:* Apple themselves picked this path over live-generation; that's a strong endorsement.

**[X2]** *Siri orb (iOS 15+).* Morphing gradient sphere using WebGL or static SVG with animated gradient stops. → Replace waveform with a 32px gradient orb; opacity 0.4 idle, 1.0 live. *Novelty:* Abstracts away from "audio = waveform" mental model.

**[X3]** *Apple Watch "Breathe" app.* Slow 4-second expanding/contracting flower. → CSS-keyframed SVG flower, 4s `ease-in-out` loop. *Novelty:* Breathing rate matches human calm response; pairs with mindfulness aesthetic.

**[X4]** *macOS "Dictation" three-dot pulse.* Three dots, staggered opacity animation. → `<div>` with three children, CSS animation-delay offsets. *Novelty:* System-level pattern, zero cost, universally understood.

**[X5]** *AirPods "connected" toast (iOS).* Tiny icon + connection quality bar. → Add a "mic quality" meter next to the record button. *Novelty:* Useful information, not decoration.

**[X6]** *iMessage typing indicator (three animated dots).* Same as [X4] but horizontal. → `...` bouncing dots. *Novelty:* Signifies "waiting for input," which is exactly what idle state means.

**[X7]** *macOS "Now Playing" in Control Center — green eq bars.* Discrete 4-bar equalizer that steps at audio envelope. → Discrete 4-bar CSS-animated glyph, 10 Hz stepped animation. *Novelty:* Familiar, compact, cheap.

### Domain 2 — Streaming / music apps

**[X8]** *Spotify "Now Playing" bars in sidebar.* Tiny 3-bar equalizer next to the song title. → Replicate as an idle "listening" indicator at 20% size. *Novelty:* Miniaturization; budget is proportional to area.

**[X9]** *YouTube's "live" red dot (pulsing).* 8px red dot, CSS pulse animation. → Replace waveform with a single pulsing dot when idle. *Novelty:* Radical minimalism; "alive" signal is literally the minimum possible.

**[X10]** *SoundCloud's orange waveform (static).* Entire waveform is a pre-rendered PNG of the *expected* audio — not animated. → Idle shows a fixed "sample" waveform (not user's); live replaces with real data. *Novelty:* Static waveform can still *feel* like a visualizer; zero motion.

**[X11]** *Twitch audio meter (during streams).* Segmented VU-meter style. → 10 vertical bars, each as a `<div>`, CSS `animation-delay`-staggered. *Novelty:* VU-meter retro aesthetic; discrete frames, cheap.

**[X12]** *Discord "voice channel" animated ring.* Glowing ring around user avatar when in voice. → Ring around the mic icon only when connected to input. *Novelty:* Ring-based affordance; border-only, outside blur.

### Domain 3 — Terminals / retro / ASCII

**[X13]** *Winamp 1.x spectrum analyzer.* Fixed 20-band equalizer, heights vary. Classic. → Skeuomorphic Winamp-style band meter as a Lottie export. *Novelty:* Instant recognition for older users, novelty for younger.

**[X14]** *ASCII spinner (|/-\\).* Unicode text that rotates via 1Hz setInterval. → `<span>{frames[tick % 4]}</span>`; stunts at character level. *Novelty:* Terminal aesthetic; essentially free.

**[X15]** *Matrix code rain (Cmatrix).* Falling Unicode characters. → CSS-animated column of Unicode glyphs with opacity gradient. *Novelty:* Extreme aesthetic commitment; may clash with glass design but visually striking.

**[X16]** *`htop` / `btop` gradient bars.* Multi-color CPU usage bars. → Could double as actual CPU monitor (meta!). *Novelty:* Function + form.

**[X17]** *Old iPod "now playing" eq glyph.* 3-bar animated eq, monochrome. → CSS-keyframed SVG, 3 rects. *Novelty:* Nostalgic + minimal.

### Domain 4 — Games / interactive

**[X18]** *League of Legends "ability cooldown" radial sweep.* Radial progress that reveals itself. → Radial progress around the mic icon as idle indicator; fills when recording starts. *Novelty:* Functional + decorative.

**[X19]** *Horizon / Zelda "breath of the wild" stamina meter.* A meter that recovers slowly when not being used. → Meter that empties while recording, refills while idle (replaces need for an independent animation). *Novelty:* Visualizer is state, not decoration.

**[X20]** *Starcraft unit portrait animation.* Portrait of the "speaker" idly blinks. → An `<img>` of a mic icon that blinks at 0.2Hz via opacity animation. *Novelty:* Character-portrait aesthetic.

**[X21]** *Super Mario "spinning coin" (frame-by-frame sprite).* 4-frame sprite animation at 4fps via `steps(4)`. → Record-button sprite that spins slowly when idle. *Novelty:* 4 frames at 4fps = 1/15th the cost of 60Hz canvas.

### Domain 5 — Hardware / ambient / physical

**[X22]** *Mac sleep-mode breathing LED.* LED opacity sinusoid at 0.25Hz. → `<div>` with CSS keyframe on opacity, 4-second cycle. *Novelty:* Hardware-native pattern, cheapest possible animation.

**[X23]** *Echo Show "Alexa listening" teal ring.* Gradient teal ring around screen edge. → Apply a CSS `box-shadow` ring around the `<GlassCard>` itself, pulsing slowly. *Novelty:* Fixture animation (border), outside inner blur.

**[X24]** *Tesla "sentry mode" camera indicator.* Red dot appears/disappears on event. → Dot appears when microphone is ready, disappears when sleeping. *Novelty:* Binary signal, zero animation.

**[X25]** *Nest Cam LED.* Solid color = ready; blinking = recording. → Two states, CSS class swap, no continuous animation. *Novelty:* State-based, not time-based.

**[X26]** *Smart display "welcome" screensaver.* Slow kenburns on a photo. → Use a subtle 30-second CSS `transform: scale(1) → scale(1.05)` on a background gradient. *Novelty:* Animation period is so long it feels static; cost is negligible over the period.

### Domain 6 — Print / architecture / physical world

**[X27]** *Neon sign "buzzing" flicker.* Rare, random 0.1s opacity drops. → Random setTimeout at 15-60s intervals for a tiny flicker. *Novelty:* Budget is <1% of continuous animation; feels alive.

**[X28]** *Campfire / candle flame (naturalistic).* Looped WebP of a tiny candle. → An unexpected metaphor for "listening" — the flame represents alert attention. *Novelty:* Metaphoric leap; might be too weird but memorable.

**[X29]** *Lighthouse beacon (sweeping ring).* Slow 360° sweep. → CSS `rotate` keyframe on an SVG sector, 5-second rotation. *Novelty:* Timeless pattern; evokes "always listening."

**[X30]** *Architectural "indicator lamp" aesthetic.* Brushed-metal + single glowing dot. → Borrow industrial-panel aesthetic; dot + frame + label. *Novelty:* Rejects the "waveform" trope entirely.

### Domain 7 — Timekeeping / rhythmic

**[X31]** *Clock "seconds hand" ticking.* Discrete 1Hz tick. → Subtle CSS animation at 1Hz; the visualizer becomes a time indicator. *Novelty:* Lowest plausible framerate; useful for showing "recording time" when live.

**[X32]** *Metronome pendulum.* 1Hz side-to-side swing. → CSS `translateX` keyframe at the speaker's selected BPM (or default 60 BPM). *Novelty:* Pairs with music/podcast use cases.

**[X33]** *Morse code-style dot/dash pattern.* Spell out `READY` in Morse on a single dot's brightness. → Easter egg for audio nerds. *Novelty:* Functional + playful.

### Domain 8 — Biological / natural

**[X34]** *Heart-rate monitor line (slow).* Classic medical EKG waveform, 1 beat per second. → Pre-baked SVG path with `animate` on `stroke-dashoffset`. *Novelty:* Retired medical aesthetic; `<animate>` is SMIL, compositor-accelerated.

**[X35]** *Jellyfish pulse.* Simple scale animation + opacity. → CSS `transform: scale()` keyframe on a radial-gradient bg, 2s cycle. *Novelty:* Organic shape; pairs with calming aesthetic.

**[X36]** *Firefly / bioluminescence.* Random brief glow events. → Multiple small dots, each with random-delayed CSS glow animations. *Novelty:* Randomness via staggered `animation-delay`.

### Domain 9 — Non-visualization ideas (ambient feedback)

**[X37]** *Audio ping on state change.* Subtle "ding" when mic activates. No visual animation at all. → Hardware-engineer approach: audio feedback, not visual. *Novelty:* Orthogonal modality; could complement any visual.

**[X38]** *Haptic feedback via Electron.* Vibrate trackpad briefly on mic-ready. → Zero visual animation; tactile cue. *Novelty:* Out of scope for most of the UI but worth noting.

**[X39]** *Status line text that changes subtly.* "Ready", "Listening", "Waiting for mic", rotating every 20 seconds. → Typewriter-text animation on the existing "Idle — awaiting input" label (already at SessionView.tsx:1841). *Novelty:* Re-use existing text element; no new surface.

**[X40]** *Window title-bar color pulse.* Electron API can animate the title-bar. → Extremely subtle color shift in the title-bar; visible only peripherally. *Novelty:* OS-chrome usage; exotic.

### Phase 3 Tally

- **40 ideas** across 9 domains.
- **Surprising/standout picks:**
  - **[X1] iOS Now Playing video** — confirms your starter intuition with industry precedent (Apple ships a video asset, not live-rendered).
  - **[X10] static waveform** — completely sidesteps the motion question.
  - **[X22] Mac sleep-mode breathing LED** — 0.25Hz opacity sinusoid; plausibly the cheapest way to say "alive."
  - **[X27] neon sign flicker** — event-driven with <1% budget.
  - **[X33] Morse code "READY"** — functional Easter egg.
  - **[X19] stamina meter** — makes the animation carry actual state (recording time left / CPU headroom / etc).
- **Cross-cuts with Phase 1/2:**
  - [X1] = concrete realization of [AR8] + [S3]
  - [X4] / [X6] / [X7] = concrete realizations of [AR13]
  - [X22] / [X14] / [X20] = concrete realizations of [AR10] + [AR9]
  - [X9] / [X24] / [X25] = concrete realizations of [AR14] (idle-vs-live distinct)
- **Total ideas across all three phases:** 20 (Phase 1 assumption flips) + 46 (Phase 2 SCAMPER) + 40 (Phase 3 cross-pollination) = **106 ideas**.

---

## Phase 4: Solution Matrix

**Goal:** Score the strongest ~18 candidates (from Phases 2-3, grouped where overlapping) on 6 dimensions, then rank by composite score and produce a shortlist ready for spec/PR handoff.

### Scoring dimensions

| Dim | Meaning | Scale |
|---|---|---|
| **CPU** | Idle renderer CPU cost vs baseline (current silent canvas = 0, pre-048dba8 = 100) | 0 (free) → 100 (worst) |
| **GPU** | Idle compositor/blur re-sample cost vs baseline | 0 → 100 |
| **Quality** | Visual quality / "glass" brand cohesion | 1 (weak) → 5 (great) |
| **Effort** | Implementation effort | S / M / L |
| **Risk** | Cross-platform regression risk (Linux Wayland + Win11 + macOS) | L / M / H |
| **Guard** | Can we write a cheap regression guard (lint / contract / CI)? | ✅ / ⚠️ / ❌ |

### Candidate pool (grouped & normalized)

**Group A — "Do the minimum"**

| ID | Idea | CPU | GPU | Quality | Effort | Risk | Guard |
|---|---|---|---|---|---|---|---|
| **P4-1** | [AR1]/[E34]/[E36] — *Ship nothing (keep current silent canvas)* | 0 | 0 | 2 | S | L | ✅ |
| **P4-2** | [X9] — *Single pulsing red/green dot* (CSS `animation` on a 6px div) | 2 | 1 | 2 | S | L | ✅ |
| **P4-3** | [X22] — *Breathing LED (0.25Hz opacity sinusoid on a 8px div)* | 2 | 1 | 3 | S | L | ✅ |
| **P4-4** | [C14] — *99%-static + 1-sec "breath" every 60 sec* (setTimeout-scheduled) | 1 | 1 | 3 | S | L | ✅ |
| **P4-5** | [X39] — *Animated status text only (SessionView.tsx:1841)* | 1 | 0 | 2 | S | L | ✅ |

**Group B — "Pre-baked asset" (user's starter idea family)**

| ID | Idea | CPU | GPU | Quality | Effort | Risk | Guard |
|---|---|---|---|---|---|---|---|
| **P4-6** | [S3]/[X1] — *Muted autoplay `<video>` MP4 of the sim* | 5 | 40¹ | 4 | M | M² | ⚠️ |
| **P4-7** | [S2] — *Animated WebP `<img>`* | 3 | 40¹ | 4 | S | L | ✅ |
| **P4-8** | [S1] — *Lottie JSON + lottie-web* | 8 | 30¹ | 4 | M | L | ⚠️ |
| **P4-9** | [S7] — *CSS steps() sprite sheet (20 frames)* | 2 | 30¹ | 3 | S | L | ✅ |

¹ *GPU cost reflects blur re-sample invalidation if rendered inside the GlassCard. Combine with [AR5]/[AR7] to drop GPU to 2-5.*
² *`<video>` element codecs: H.264 is safe on all Chromium/Electron builds; autoplay restrictions disabled in Electron.*

**Group C — "Compositor-only motion"**

| ID | Idea | CPU | GPU | Quality | Effort | Risk | Guard |
|---|---|---|---|---|---|---|---|
| **P4-10** | [S5]/[AR10] — *Pure CSS keyframes on a pseudo-element (outside blur)* | 0 | 3 | 3 | S | L | ✅ |
| **P4-11** | [S8] — *Static SVG + CSS mask-image shimmer* | 0 | 3 | 4 | S | L | ✅ |
| **P4-12** | [C15] — *Static canvas frame + CSS `filter: hue-rotate` on outer wrapper* | 0 | 5 | 4 | S | M³ | ⚠️ |
| **P4-13** | [X23] — *CSS `box-shadow` ring around the GlassCard, pulsing* | 0 | 5 | 3 | S | L | ✅ |
| **P4-14** | [C13] — *CSS-animated gradient traveling along the GlassCard border* | 0 | 3 | 4 | M | L | ✅ |

³ *hue-rotate on an element that has backdrop-filter is quirky — may behave inconsistently. Must prototype.*

**Group D — "Hybrid / two-component"**

| ID | Idea | CPU | GPU | Quality | Effort | Risk | Guard |
|---|---|---|---|---|---|---|---|
| **P4-15** | [AR18]+[C12] — *`IdleVisualizer` (Lottie/CSS) + `LiveAudioVisualizer` (canvas) + cross-fade* | 0-5 | 5-10 | 5 | M-L | M | ⚠️ |
| **P4-16** | [R44] — *Stacked layers: live canvas always rendered at z:0 + idle top layer at z:1, opacity swap* | 1 | 3 | 4 | M | L | ✅ |
| **P4-17** | [AR5]+[S2] — *Animated WebP rendered outside GlassCard blur region (z-index above card)* | 3 | 3 | 4 | M | L | ✅ |

**Group E — "Rethink the framing"**

| ID | Idea | CPU | GPU | Quality | Effort | Risk | Guard |
|---|---|---|---|---|---|---|---|
| **P4-18** | [X19] — *Stamina/time-meter (visualizer encodes recording duration or CPU headroom)* | 2 | 3 | 5 | L | L | ✅ |
| **P4-19** | [R46] — *Stillness that becomes motion — static until audio, then explodes into waveform* | 0 | 0 | 5 | S | L | ✅ |
| **P4-20** | [P31] — *Visualizer IS the record button; hover = subtle pulse* | 1 | 2 | 4 | M | L | ✅ |
| **P4-21** | [X33] — *Morse code "READY" easter egg on a single pulsing dot* | 2 | 1 | 3 | S | L | ✅ |

### Composite ranking

**Weights (subjective, tunable):** CPU 30% · GPU 30% · Quality 20% · Effort 10% · Risk 5% · Guard 5%. Lower is better (except Quality, inverted).

Computing `score = 0.3 × (CPU/100) + 0.3 × (GPU/100) + 0.2 × (1 - Quality/5) + 0.1 × effort-penalty + 0.05 × risk-penalty + 0.05 × guard-penalty`. Lower = better.

**Ranked shortlist:**

| Rank | ID | Idea | Score | Headline |
|---|---|---|---|---|
| **1** | **P4-19** | Stillness-that-becomes-motion ([R46]) | **0.00** | Perfect score on cost; highest aesthetic leverage for lowest engineering effort. The transition IS the animation. |
| **2** | **P4-10** | Pure CSS pseudo-element outside blur ([S5]+[AR5]) | **0.10** | Compositor-only; zero JS; outside blur = no multiplier. |
| **3** | **P4-1** | Do nothing (null hypothesis, [AR1]) | **0.12** | The baseline. If P4-19 fails design review, this is the fallback. |
| **4** | **P4-11** | Static SVG + CSS shimmer ([S8]) | **0.12** | Shopify-tier skeleton shimmer; well-understood; very cheap. |
| **5** | **P4-4** | 99%-static + 60s breath ([C14]) | **0.14** | Budget is 1 sec of animation per minute — literally 1.7% of continuous. |
| **6** | **P4-13** | CSS box-shadow ring on GlassCard border ([X23]) | **0.15** | Border-only, outside blur; Echo Show aesthetic. |
| **7** | **P4-3** | Breathing LED ([X22]) | **0.15** | Tiny dot, 0.25Hz sinusoid; hardware-native pattern. |
| **8** | **P4-16** | Stacked layers + opacity swap ([R44]) | **0.16** | Clean implementation of the hybrid pattern; the live canvas is always mounted but gated by `isActive`. |
| **9** | **P4-17** | Animated WebP outside blur ([AR5]+[S2]) | **0.17** | User's starter idea, fixed to sidestep blur multiplier. |
| **10** | **P4-15** | Full two-component hybrid ([AR18]+[C12]) | **0.17** | Most flexible architecture, more effort. |
| 11 | P4-18 | Stamina / time meter | 0.18 | Useful state, but new UX concept. |
| 12 | P4-12 | Static canvas + hue-rotate | 0.20 | Elegant but cross-platform quirky. |
| 13 | P4-14 | Border-traveling gradient | 0.20 | Aesthetic, more engineering. |
| 14 | P4-7 | Animated WebP in-place | 0.20 | Simpler than P4-17 but pays the blur multiplier. |
| 15 | P4-8 | Lottie | 0.21 | Adds ~50KB runtime dep; low win vs WebP. |
| 16 | P4-20 | Visualizer-is-record-button | 0.21 | Interesting UX but bigger redesign. |
| 17 | P4-9 | CSS sprite sheet | 0.22 | Works but no perf win over P4-7. |
| 18 | P4-2 | Single pulsing dot | 0.22 | Cheap, but quality lower than P4-3's breath. |
| 19 | P4-5 | Animated text only | 0.23 | Too subtle to count as "restoring animation." |
| 20 | P4-21 | Morse-code easter egg | 0.24 | Fun but too niche as primary solution. |
| 21 | P4-6 | `<video>` MP4 | 0.25 | Best visual quality among pre-baked, but blur multiplier if not combined with [AR5]. |

### Shortlist analysis

**Top 3 actionable recommendations:**

**🥇 P4-19 — Stillness-that-becomes-motion ([R46]).** Canvas stays painted at `ctx.clearRect` state (i.e. truly blank) during idle, OR paints a single static "at-rest" frame once and never again. When audio is detected (`analyserNode` becomes non-null), the canvas smoothly transitions into the live waveform via the existing drawReal path. **No idle animation at all, but the *transition* into the live state is the animation.** The user's eye gets the "wake up" moment they're subconsciously looking for. Cost: literally 0 in idle. Effort: S — it's mostly just "when `isActive` flips true, start drawReal immediately with a brief opacity fade-in on the canvas."

**🥈 P4-10 — Pure CSS pseudo-element outside blur ([S5]+[AR5]).** A `::after` pseudo-element on the GlassCard's outer container (not the inner blurred region) hosts a gentle CSS-keyframe animation (e.g. a slowly rotating gradient or a subtle wave path). Because it's outside the blur, there's no re-sample multiplier. Cost: ~zero CPU, trivial GPU (compositor transforms). Effort: S. Gives you the "there's motion somewhere" feeling without re-litigating the canvas.

**🥉 P4-4 — 99%-static + 60s breath ([C14]).** The canvas (or SVG) renders a single static frame. Once per minute, a 1-second CSS opacity breath (0.7 → 1.0 → 0.7) plays. Budget is literally 1.7% of continuous animation. Effort: S. "Once per minute" feels like "heartbeat" rather than "animation," which maps well to the feedback job from [AR2].

**Hybrid spec (combining winners):** Use **P4-19's stillness-into-motion transition** as the primary engagement surface, and **P4-10's CSS pseudo-element (or P4-13's box-shadow ring)** as a very subtle "the app is alive" cue that runs quietly outside the blur region. Cost of this combination: ~0 CPU, ~3-5 GPU (one compositor-level transform outside blur). Quality: high (two separate cues: "alive" always, "listening" on state change). Effort: S-M.

**What to skip:**
- `<video>` / WebP / Lottie / sprite-sheet family (P4-6 through P4-9): inferior once you realize the blur multiplier still applies unless you go to P4-17 tier. And if you're doing P4-17, you're already in two-surface territory (P4-15/P4-16), which is strictly better.
- The "do nothing" baseline P4-1 is the safety net: if P4-19's implementation has any surprises on review, ship P4-1 and close the issue.

---

## Session Summary

**Methodology:** AI-Recommended 4-phase sequence — Assumption Reversal (surface/flip 20 framing assumptions) → SCAMPER (46 ideas across 7 lenses) → Cross-Pollination (40 ideas across 9 domains including iOS, Spotify, terminals, hardware, print, biology) → Solution Matrix (score 21 strongest candidates on 6 dimensions, rank by weighted composite).

**Conclusion:** The user's starter idea (pre-record the animation loop and replay) is **valid but incomplete** — it only wins back half the 048dba8 savings, because the canvas still sits inside a `backdrop-blur-xl` GlassCard, and the blur re-sample cost applies to *any* per-frame canvas content change, video or not.

**Three stronger paths surfaced:**

1. **P4-19 stillness-into-motion (recommended primary)** — don't run an idle animation at all; instead, make the *transition from idle to live* the animation moment. Gives the user the "wake up" perceptual cue they subconsciously expect, with literally zero idle cost.
2. **P4-10 CSS pseudo-element outside blur (recommended secondary cue)** — compositor-only ambient motion on a surface that escapes the GlassCard's blur-re-sample coupling. Near-free.
3. **P4-4 60-second breath (cheapest continuous)** — 1.7% of continuous animation budget, feels like "heartbeat."

**If the user still wants the pre-recorded loop idea:** combine [AR5] with [S2] (animated WebP outside the blur region via absolute positioning or a sibling layer, z-index above the card but outside its blur source). That's **P4-17**, ranked #9 — fine but dominated by the top-3 picks.

**The deepest insight from Phase 1:** [AR5] — the "motion outside blur" flip — is the structural unlock that everything hinges on. It turns a hard problem ("the canvas is stuck inside a blur region") into an easy one ("put the motion somewhere else").

**Ideas generated:** 106 (Phase 1: 20, Phase 2: 46, Phase 3: 40).
**Techniques used:** Assumption Reversal, SCAMPER Method, Cross-Pollination, Solution Matrix.

### Creative Facilitation Narrative

The session adapted standard brainstorming techniques for a UI+perf tradeoff: the "creative quantity" phase focused on generating implementable candidates across a wide solution-engine space (Lottie/WebP/video/SVG/CSS/sprite/canvas/text/unicode/native), while the Cross-Pollination phase deliberately pushed into domains outside UI engineering (hardware LEDs, architecture, biology, ASCII) to escape semantic clustering. The LLM acted as primary generator; the user steered by correcting the Mac-specific framing (commit 048dba8 savings are cross-platform, not Mac-only) and by choosing Assumption Reversal over First Principles for Phase 1 — a choice that produced the [AR5] structural unlock that reshaped the entire downstream candidate set.

The session's most valuable moment was recognizing in Phase 2 that the user's starter "record and replay" idea solves only the JS-side of the cost (which is ~50% of the 048dba8 win) but not the GPU-side (blur re-sample), and that fixing *both* requires moving the animation surface outside the GlassCard — after which many previously-equivalent candidates suddenly ranked very differently.

### Session Highlights

**Breakthrough moments:**
- Discovery that the 048dba8 savings are ~50/50 JS vs GPU — video-on-canvas only recovers the JS half.
- Recognition that [AR5] (motion outside blur) is the structural unlock that reshapes the whole solution space.
- The P4-19 "stillness-into-motion" idea, which solves the problem by denying the premise — the animation isn't idle, it's the transition.
- Apple's iOS Now Playing wave being a pre-recorded video [X1] as industry precedent for the user's starter idea.
- The three-philosophy framing from Phase 3: minimal affordance / pretty-but-cheap / functional-state-encoding — which stratified the Phase 4 scoring cleanly.

**Decisions for next session (implementation):** Start with P4-19 (stillness-into-motion) as a spike PR. If design review prefers continuous motion, combine with P4-10 or P4-13 for ambient cue. P4-1 (do nothing) is the safety net if neither lands.




