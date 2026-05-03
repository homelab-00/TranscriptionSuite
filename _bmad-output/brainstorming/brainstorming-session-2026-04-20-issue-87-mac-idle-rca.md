---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Root-cause hypotheses for GH Issue #87: high idle CPU/GPU on Mac (Apple Silicon) when TranscriptionSuite dashboard is visible on screen'
session_goals: 'Generate a ranked set of root-cause hypotheses and a diagnostic plan the user (or a Mac-using reporter) can execute, given that the user has no Apple Silicon hardware for direct testing'
selected_approach: 'progressive-flow'
techniques_used: ['Reverse Brainstorming', 'Five Whys', 'Solution Matrix', 'Decision Tree Mapping']
ideas_generated: 105
technique_execution_complete: true
top_clusters:
  - 'Cluster A: AudioVisualizer rAF (C1) × stacked backdrop-blur (C2), amplified by Mac Metal platform (C3)'
  - 'Cluster B: Model-tab layer-pool churn — many blurred GlassCards in scrollable list (C4)'
primary_fix_actions:
  - 'Gate AudioVisualizer rAF on isActive prop'
  - 'React.memo + stable keys on ModelManagerTab rows (virtualize if >20 models)'
  - 'ui-contract blur-depth budget rule'
context_file: ''
session_continued: true
continuation_date: '2026-04-25'
extension_topic: 'Blur GPU overhead reduction — actual cost reduction beyond the C2-b guardrail (committed 97c525d)'
extension_status: 'complete-decisions-recorded'
extension_techniques: ['Morphological+SCAMPER', 'Affinity+2x2', 'Decomposition+WhatIf', 'PhasedRoadmap']
extension_ideas_generated: 130
extension_phase_1_domains: 13
extension_pr_actions: ['F1 codify tiers', 'F2 native vibrancy', 'F3 flatten nested blurs', 'F4 drop scroll-edge blur', 'F5 contain hints', 'F6 kill transitions on blur', 'F7 personal radius A/B', 'F8 nested-blur contract rule']
extension_waves: 4
extension_implementation_sprints: 4
extension_predicted_impact_mac: '75-95% idle GPU reduction after Wave 3'
extension_top_actions:
  - 'F2 native macOS vibrancy + Windows Mica (highest single-shot)'
  - 'F1 codify T1-T4 tiers in design-language.md (foundation)'
  - 'F3 flatten nested blurs (NotebookView, App.tsx, AudioNoteModal)'
extension_decisions_recorded: '2026-04-25'
f7_research_owner: 'user'
w4_status: 'deferred-to-deferred-work-md'
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-04-20

## Session Overview

**Topic:** Root-cause hypotheses for GH Issue #87 — on Mac M4 Pro (Sequoia 15.x, Metal build, v1.3.3), the dashboard consumes high CPU & GPU *only while the app window is visible on screen*; consumption drops when the window is covered. Reporter also notes screen flicker on the Model tab and scroll redraw artifacts.

**Goals:**
- Enumerate plausible root causes (broad, not narrow)
- Distinguish which hypotheses are testable *without* a Mac vs. which require a Mac reporter
- Produce a prioritized diagnostic plan and candidate code-side experiments

**Constraint:** No Apple Silicon Mac available to the facilitator. All hypothesis-testing must be designed so that it can be validated by (a) static code inspection, (b) the reporter on issue #87, or (c) a collaborator with Mac hardware (e.g. @twilsonco).

### Context Guidance

_No external context file loaded._

### Initial Evidence (from issue thread)

- Symptom appears **only when window is visible**; hiding/covering the window drops usage → strong signal for GPU-accelerated compositing / CSS effects.
- Reporter specifically notes screen flicker + partial repaint artifacts when entering **Model tab** and while scrolling.
- Collaborator @twilsonco: "runaway css styling; likely a blur effect."
- Owner @homelab-00: agrees it's Dashboard, not models; probably the many blur effects.
- Screenshots show CPU ~20%+ and GPU counter non-trivial while idle.

### Initial Codebase Signals (pre-brainstorm scan)

- **21 files** in `dashboard/` reference `backdrop-filter` / `backdrop-blur` / `filter: blur`.
- **27 files** reference `setInterval` / `requestAnimationFrame` / CSS `animation:` / `@keyframes`.
- Suspected hot spots from filenames alone: `Sidebar.tsx`, `GlassCard.tsx`, `ActivityNotifications.tsx`, `FullscreenVisualizer.tsx`, `ModelManagerTab.tsx` / `ModelManagerView.tsx`, `AudioVisualizer.tsx`, `src/index.css`.

---

## Technique Selection

**Approach:** Progressive Technique Flow
**Journey Design:** Hypothesis generation → root-cause drilling → feasibility matrix → diagnostic triage tree

- **Phase 1 — Exploration:** Reverse Brainstorming ("what could burn idle cycles?")
- **Phase 2 — Pattern Recognition:** Five Whys (does each top cluster explain visibility-gating + Model-tab flicker + scroll artifacts?)
- **Phase 3 — Development:** Solution Matrix (hypothesis × testable-without-Mac × likelihood × diagnostic)
- **Phase 4 — Action Planning:** Decision Tree (triage script for Mac reporter)

**Journey Rationale:** No Mac access → we need to rank hypotheses by how much evidence we can gather *without* target hardware and produce a minimum-effort diagnostic plan the reporter can execute.

---

## Phase 1: Reverse Brainstorming — "How could the dashboard burn idle CPU/GPU while visible?"

**Facilitation note:** LLM-generated with static codebase evidence. 50+ hypotheses, domain-pivoted every 10 to combat semantic clustering. Each hypothesis anchored to code location where possible.

### Domain A — CSS compositing & backdrop-filter (ideas 1–10)

**[A1] AudioVisualizer-always-animating (SMOKING GUN)**
- *Concept:* `AudioVisualizer.tsx:134-141` calls `requestAnimationFrame(draw)` with no gate on recording/visibility/audio flow. It runs at 60 Hz forever while mounted; `SessionView.tsx:1875` mounts it unconditionally. When no `analyserNode`, it falls back to `drawSimulation()` which runs `Math.sin` math every frame plus canvas re-paint.
- *Novelty:* The 2D canvas paint every frame is GPU-submitted on macOS even if "idle" — and the simulation branch means **even with no audio the loop never stops**.
- *Mac multiplier:* Metal compositor counts canvas updates on the GPU meter in a way Linux/Windows don't surface.

**[A2] Backdrop-blur stack on Sidebar**
- *Concept:* `Sidebar.tsx:219` uses `backdrop-blur-2xl` on a full-height always-visible element.
- *Novelty:* `backdrop-blur` requires sampling everything beneath it every frame. Stacked with `transition-all duration-300` on collapse, even mouse hover on unrelated elements can trigger a repaint of the blurred region.

**[A3] Blur stacking in glass modals over glass surface**
- *Concept:* `design-language.md:61` explicitly warns against "Blur stacking: excessive `backdrop-blur` on nested layers." Many modals (`SettingsModal`, `AboutModal`, `UpdateModal`, `AudioNoteModal`) apply `backdrop-blur-xl` *on top of* a page that already has blurred surfaces.
- *Novelty:* This is documented as a known pitfall by the project itself — yet open modals/overlays still stack.

**[A4] GlassCard as ubiquitous blur**
- *Concept:* `GlassCard.tsx:18` applies `backdrop-blur-xl` to every card in the UI. The Model tab likely renders dozens of these cards (one per model).
- *Novelty:* N cards = N composited layers needing per-frame sampling. Scales with content, explaining why Model tab (many items) is worst.

**[A5] NotebookView full-surface backdrop-blur**
- *Concept:* `NotebookView.tsx:725,727` applies `backdrop-blur-xl` + `backdrop-blur-md` on the entire view container plus its header → two nested blur surfaces over the full visible area.
- *Novelty:* Pure static UI costs real GPU.

**[A6] Fullscreen visualizer backdrop-blur-3xl**
- *Concept:* `FullscreenVisualizer.tsx:50` uses `backdrop-blur-3xl` — that's the maximum Tailwind blur (64 px). If opened and closed, does the overlay properly detach?
- *Novelty:* Even briefly displayed 3xl blur forces the compositor into high-radius kernel convolutions.

**[A7] Bug/About/Add/Star modals present but invisible**
- *Concept:* `BugReportModal`, `AboutModal`, `AddNoteModal`, `StarPopupModal` all use `translate-y-[100vh]` / `opacity-0` + a wrapping backdrop. If React keeps them mounted (not unmounted) while `isVisible=false`, the compositor still has to reason about the blur layer.
- *Novelty:* Modals that "slide off" aren't the same as unmounted modals. Chromium may still maintain the blurred layer.

**[A8] Gradient + blur combo**
- *Concept:* `SessionView.tsx:1174,1774,1799,2279` applies `bg-linear-to-b/t from-white/10 to-transparent backdrop-blur-sm` on scroll-edge fade elements. These are always rendered.
- *Novelty:* A gradient + blur is double compositor work for a purely decorative scroll affordance.

**[A9] will-change or transform implicit layer promotion**
- *Concept:* The project uses many `translate-y-*`, `transition-all`, `scale-*` classes. Tailwind's `transition-*` implies `will-change` on some browsers, promoting layers to GPU-backed even when static.
- *Novelty:* Hidden cost of transition classes — they never "rest" on Metal.

**[A10] Scroll-bar gradient overlays redraw on every scroll event**
- *Concept:* The `bg-linear-to-*-from-white/10-to-transparent backdrop-blur-sm` fade elements sit on every scroll container. On scroll (or on content expansion), they get repainted. Model tab = lots of items = lots of scroll = continuous repaint.
- *Novelty:* Matches the reporter's "partial repaint while scrolling" symptom directly.

### Domain B — JavaScript loops, timers, polling (ideas 11–20)

**[B11] Unthrottled rAF loop in AudioVisualizer (reinforces A1)**
- *Concept:* Same mechanism as A1 but viewed through the JS lens: the `draw` closure allocates a Uint8Array per frame when `analyserNode` is provided (line 116, `new Uint8Array(analyserNode.fftSize)` inside `drawReal`). That's 60 allocations/sec → GC pressure.
- *Novelty:* Even the "real" branch has a per-frame allocation bug.

**[B12] UpdateBanner `nowTimer` 1Hz forever**
- *Concept:* `UpdateBanner.tsx:401-403` creates `setInterval(() => setNow(Date.now()), NOW_TICK_MS)` to recompute "now" for snooze expiry. This re-renders the banner every tick while mounted — even when no update is pending.
- *Novelty:* A "snoozed timer" for an update that hasn't arrived, continuously re-rendering.

**[B13] UpdateBanner `statusTimer` poll**
- *Concept:* Same file, line 343: `setInterval(pollStatus, STATUS_POLL_MS)`. Polls the update manager repeatedly.
- *Novelty:* IPC + React re-render every STATUS_POLL_MS, mounted throughout the app.

**[B14] WebSocket keepalive ping**
- *Concept:* `src/services/websocket.ts:548` sets `pingTimer = setInterval(...)`. This sends a JSON frame on every interval.
- *Novelty:* Fine in isolation; adds to baseline wake count that prevents renderer idle.

**[B15] useDocker poll loop**
- *Concept:* `src/hooks/useDocker.ts:202` `setInterval(async () => { ... })` — polls Docker status.
- *Novelty:* Hits IPC repeatedly. On Mac (Docker Desktop), each call has higher overhead than Linux.

**[B16] useStarPopup / useSessionWatcher / useNotebookWatcher 10s polls**
- *Concept:* Multiple `setInterval(..., 10_000)` in hooks. Each wakes React.
- *Novelty:* Individually tiny; collectively baseline-raising.

**[B17] useAuthTokenSync poll**
- *Concept:* `src/hooks/useAuthTokenSync.ts:132` — another interval.
- *Novelty:* Token sync typically cheap, but if it writes React state, every tick = re-render of consumers.

**[B18] useWordHighlighter rAF**
- *Concept:* `src/hooks/useWordHighlighter.ts:185,188` — rAF loop for word-level highlighting at 60fps.
- *Novelty:* Active during playback; if not properly cancelled when playback pauses or component hides, it keeps running.

**[B19] AudioNoteModal interval 689 + 725**
- *Concept:* Two `setInterval` calls in `AudioNoteModal.tsx`. If the modal leaks its intervals on close, it's a permanent background timer.
- *Novelty:* Suspected leak location.

**[B20] AppState pending timer**
- *Concept:* `electron/appState.ts:159` — `setInterval` in main process. `__tests__/appState.test.ts:441` explicitly references "orphan setInterval timers" — suggesting leaks have been an issue before.
- *Novelty:* Main-process timers don't show up on renderer CPU but do wake the event loop.

### Domain C — React re-render storms (ideas 21–30)

**[C21] UpdateBanner re-renders every 1s triggers context consumers**
- *Concept:* If `setNow(Date.now())` updates a state that's consumed by a context provider or a widely-shared parent, re-renders propagate.
- *Novelty:* Mac devtools surface this readily; Linux devs often miss subtree re-renders.

**[C22] Non-memoized ModelManagerTab list**
- *Concept:* `ModelManagerTab.tsx` iterates `MODEL_REGISTRY` and renders a GlassCard per model. If the list isn't memoized (no `React.memo` / no stable keys), a parent re-render (e.g. from `setNow` above) causes full re-creation of all model rows.
- *Novelty:* Matches "flicker on entering Model tab" — heavy re-render on mount + subsequent parent-driven re-renders causing churn.

**[C23] Uncached className string interpolations**
- *Concept:* Many components compose className via template literals referencing conditions (`${isVisible ? ... : ...}`). Every re-render creates a new string → React reconciles className even when the actual classes are unchanged.
- *Novelty:* Individually cheap, but at N=100 elements × 60 Hz (if something forces a re-render loop), material.

**[C24] Context providers re-rendering whole tree**
- *Concept:* If any "always-running" timer updates a state surfaced via Context, consumers deep in the tree all re-render.
- *Novelty:* Compound effect of many individually-benign timers.

**[C25] Zustand / state store subscriptions**
- *Concept:* If the app uses a global store (Zustand, Jotai) and a subscriber selects an object (not a primitive), referential identity changes cause re-renders.
- *Novelty:* Mac-independent, but re-renders + blur = worse Mac cost.

**[C26] Activity notifications keep mounting**
- *Concept:* `ActivityNotifications.tsx:97` — notifications use `animate-in slide-in-from-right-4 fade-in` which is a continuous CSS animation during the animation window. If toasts stack up and don't dismiss, the animated class keeps spinning.
- *Novelty:* Check whether dismissal actually unmounts or just hides.

**[C27] Stale closure in useEffect creating new timer each render**
- *Concept:* If any hook has `setInterval` inside a `useEffect` with missing deps, and re-runs on parent re-render, intervals can stack.
- *Novelty:* Classic React leak pattern; `useDocker.ts`, `useAuthTokenSync.ts` are the suspects.

**[C28] Monitor hook ticking**
- *Concept:* Any hook that subscribes to mouse/scroll/resize without throttle fires on every native event. Scroll in Model tab = burst fire.
- *Novelty:* Ties scroll symptom to React re-render storm, not just CSS compositing.

**[C29] IntersectionObserver / ResizeObserver never disconnected**
- *Concept:* Observers hooked to DOM nodes that remount can leak observers.
- *Novelty:* On macOS with Metal, observer callbacks that setState cause repaints that cost real GPU.

**[C30] SessionView recalcScrollIndicators rAF on scroll**
- *Concept:* `SessionView.tsx:991,1025` — `requestAnimationFrame(recalcScrollIndicators)` on scroll events. If the scroll event fires frequently (touchpad) and the rAF chain doesn't coalesce, it runs every frame.
- *Novelty:* Matches scroll-repaint symptom.

### Domain D — macOS / Metal / Electron platform (ideas 31–40)

**[D31] Chromium's rAF throttling hides bug on Linux/Windows**
- *Concept:* Chromium aggressively throttles rAF when the window is hidden, but NOT when the window is covered yet still considered "visible" by the OS. On Mac, the definition of "occluded" is generous — Chromium may keep running full-speed until the window is truly hidden.
- *Novelty:* Explains why the bug is Mac-specific even if the underlying code is cross-platform.

**[D32] Metal's backdrop-filter is costlier than Vulkan/DirectX blur**
- *Concept:* Chromium's Metal backend implements `backdrop-filter` via per-frame `CAFilter` + render-pass. The per-frame cost on Metal is higher than Vulkan (Linux) or ANGLE-on-DX (Windows) for the same blur radius.
- *Novelty:* Cross-platform code path, Mac-specific cost profile.

**[D33] macOS Sonoma/Sequoia increased compositor aggressiveness**
- *Concept:* macOS 15 (Sequoia) changed how background-throttled apps behave vs. `displayLink`. If Electron's renderer doesn't properly negotiate display sync, it can run at ProMotion 120 Hz instead of 60 Hz.
- *Novelty:* M4 Pro + Sequoia 15 + 120 Hz ProMotion = doubled work for any rAF loop.

**[D34] No `backgroundThrottling: false` setting, but also no explicit opposite**
- *Concept:* `electron/main.ts:700-716` — `webPreferences` does NOT set `backgroundThrottling`. Default is `true` which *helps* (throttles when hidden). The symptom reported is "drops when hidden" → so throttling IS working. The problem is that when NOT hidden, the work is heavy.
- *Novelty:* Rules out backgroundThrottling bug but confirms "visible work is the culprit."

**[D35] No `app.disableHardwareAcceleration()` call**
- *Concept:* The main process never disables HW accel, so compositing goes through Metal on Mac. This is normal — but is the only knob to try for confirming "this is GPU-comp-driven."
- *Novelty:* One-line diagnostic toggle the reporter could test.

**[D36] Electron version has known macOS CPU regressions**
- *Concept:* Several Electron versions (e.g., 28.x, 30.x early) had regressions around renderer-process CPU on Apple Silicon. Need to check `electron` version in package.json against Electron's issue tracker.
- *Novelty:* May be fixed by a version bump alone.

**[D37] Chromium's `MacDisplayLink` running at ProMotion**
- *Concept:* On 120 Hz ProMotion displays, Chromium may request 120 FPS rAF callbacks. Doubles all our rAF loops' cost vs. our 60 Hz dev machines.
- *Novelty:* The M4 Pro has ProMotion.

**[D38] Color space conversion / HDR path**
- *Concept:* macOS 15 expanded HDR surfaces. Chromium may convert our sRGB backgrounds to the display's color space per frame.
- *Novelty:* Long shot; applies only if app requests a specific color space.

**[D39] Window occlusion detection off**
- *Concept:* Electron's `BrowserWindow.isVisible()` may not match macOS's NSWindow occlusion. If the app thinks it's visible (even when partially covered) and runs full-throttle, symptom matches exactly.
- *Novelty:* The reporter explicitly said "as long as it's *visibly* on screen (even when partly covered)." That phrasing is diagnostic — matches NSWindowOcclusionState not firing "hidden" until fully hidden.

**[D40] CSS subpixel AA on Retina amplifies compositor cost**
- *Concept:* Retina (×2 / ×3 DPI) means 4× the pixels to blur. `backdrop-blur-xl` at 24 px radius on a Retina 2560×1440 surface = ~7M pixels per blur sampling.
- *Novelty:* Explains why the same code is "fine" on a 1080p Linux monitor and "terrible" on a Retina Mac.

### Domain E — Polling, data flow, WebSocket (ideas 41–50)

**[E41] Server health poll on top of WebSocket**
- *Concept:* If the dashboard both polls `/health` on an interval AND holds a WebSocket open, that's double the wake rate.
- *Novelty:* Check for `fetch(...)` inside any `setInterval` in hooks.

**[E42] ModelManager cache-status refresh on render**
- *Concept:* `ModelManagerTab.tsx:55` prop `refreshCacheStatus` — if called in a `useEffect` without proper deps, may fire on each render.
- *Novelty:* Matches Model-tab flicker: entering the tab = cache refresh call = re-render cycle.

**[E43] Docker status poll makes native call per tick**
- *Concept:* Every `useDocker.ts` interval makes an IPC call that bridges to Node/Docker CLI. On Mac, process spawn / IPC cost is higher.
- *Novelty:* Mac-specific amplifier.

**[E44] SSE or WS message storm from server idle-noise**
- *Concept:* If the server pushes any "heartbeat" or "progress" message while idle (even empty), the client must deserialize + possibly re-render.
- *Novelty:* Check server-side idle emission.

**[E45] Repeated asset requests**
- *Concept:* If any component uses `<img src={dynamic}>` where `dynamic` changes identity each render, browser re-fetches.
- *Novelty:* Look for icon URLs regenerated per render.

**[E46] AuthToken refresh on every re-render**
- *Concept:* If token sync hook has `now` in its effect deps, it runs every second.
- *Novelty:* Compounds with UpdateBanner nowTimer.

**[E47] LocalStorage / IndexedDB reads in render**
- *Concept:* Synchronous `localStorage.getItem` during render; the OS treats it as a disk-backed read.
- *Novelty:* Mac's APFS vs. Linux ext4 cache semantics differ — may be slower.

**[E48] Icon library re-render penalty**
- *Concept:* `lucide-react` icons are React components rendering inline SVGs. Every re-render rebuilds the SVG tree unless memoized.
- *Novelty:* At 100+ icons across the UI × re-render rate, material CPU.

**[E49] Log viewer tail polling**
- *Concept:* If the Activity/Log view uses polling vs. WS tail, it's a file-read loop.
- *Novelty:* Check LogTerminal.tsx.

**[E50] Feature flag / config hot-reload listener**
- *Concept:* If config changes trigger a full provider re-render without selector specificity, the whole tree re-renders.
- *Novelty:* Audit for `useContext(Config)` at the root.

### Domain F — Build, install, environment (ideas 51–60)

**[F51] Version 1.3.3 installed fresh (per reporter) → no cache hydration**
- *Concept:* Reporter explicitly says "installed yesterday" — first-run path may skip cache, re-download artifacts, or keep first-run onboarding animations.
- *Novelty:* Transient-but-persistent state on first install only.

**[F52] DevTools accidentally opened or openable**
- *Concept:* `electron/main.ts:756` opens DevTools in dev mode. If the prod build path includes a stray `openDevTools()`, it devastates Mac CPU (DevTools itself uses a lot).
- *Novelty:* Check the `isDev` guard and see if any users reported DevTools visible.

**[F53] Sourcemap fetches in prod**
- *Concept:* If sourcemaps are shipped and DevTools is accidentally enabled, it does continuous map resolution.
- *Novelty:* Unlikely but cheap to rule out.

**[F54] Gatekeeper/SIP re-signing delay**
- *Concept:* First-run Mac apps go through amfid signature verification. If our app re-mmaps files repeatedly, amfid may stay hot.
- *Novelty:* Not really a Dashboard issue — mostly transient. Can be dismissed.

**[F55] Metal build shipping dev-only verbose logging**
- *Concept:* If the Metal build ships with `DEBUG=true` env or verbose logger, console writes are frequent.
- *Novelty:* Check the production build env.

**[F56] Vite dev-server accidentally shipped**
- *Concept:* If the Metal release build includes dev bundle artifacts (HMR client), the HMR websocket runs and polls.
- *Novelty:* Package inspection ruling — testable via `asar` extract.

**[F57] Electron autoUpdater / Squirrel background check**
- *Concept:* Squirrel.Mac periodically checks for updates. If our `updateManager.ts` is additive rather than replacing, we're double-checking.
- *Novelty:* Look for `autoUpdater` + our custom manager coexisting.

**[F58] Notarization trampoline process**
- *Concept:* If we're an ad-hoc signed app, macOS Gatekeeper keeps a subprocess warm.
- *Novelty:* One-time-ish; not likely the root.

**[F59] Font loading / webfont recomposition**
- *Concept:* Fresh install means first-time font resolution. macOS CoreText may be busy.
- *Novelty:* Transient; should settle after 1-2 minutes.

**[F60] Model cache check IPC on every render**
- *Concept:* `ModelManagerTab` prop `modelCacheStatus` — if built via filesystem scan per-render without memoization, it's a disk-read per interaction.
- *Novelty:* Matches Model-tab symptom specifically.

### Domain G — Wildcards / high-provocation (ideas 61–65)

**[G61] macOS low-power-mode escalation**
- *Concept:* When plugged in, ProMotion and GPU boost to max — when battery, throttled. Reporter may be plugged in while observing.
- *Novelty:* Environmental amplifier.

**[G62] Accessibility / screen-reader polling**
- *Concept:* VoiceOver or other a11y services may re-scan our app's DOM frequently, especially with many ARIA-labeled items.
- *Novelty:* Only applies if the reporter uses a11y services.

**[G63] macOS window-manager apps (e.g. Raycast, Rectangle) snooping**
- *Concept:* Third-party window managers may poll app state.
- *Novelty:* External, not our bug — worth ruling out.

**[G64] The `animate-in` Tailwind + `fade-in` classes define long-duration animations**
- *Concept:* `ActivityNotifications.tsx:97` uses `animate-in slide-in-from-right-4 fade-in duration-300`. If a notification is shown briefly then hidden (not unmounted), the animation keeps trying to run.
- *Novelty:* Need to check whether the notification system unmounts or just hides.

**[G65] Glass effect specifically on large elements in transition**
- *Concept:* `SettingsModal.tsx:1873` — `h-[85vh] w-full max-w-3xl` with `backdrop-blur-xl` + `transition-all duration-300`. Every hover state on the whole modal forces a 85vh blur re-evaluation.
- *Novelty:* Large-area blur with transitions.

---

**Phase 1 batch 1 complete: 65 hypotheses across 7 orthogonal domains.**

### Continuation batch — Phase 1 (ideas 66–105)

User elected to keep exploring. Pushing into Electron internals, memory/GC, forced-layout, accessibility, and adversarial/provocative territory.

### Domain H — Electron internals & IPC (ideas 66–75)

**[H66] IPC firehose from 94 handlers**
- *Concept:* `electron/main.ts` has 94 `ipcMain.on`/`ipcMain.handle`/`webContents.send` call sites. Every `webContents.send` wakes the renderer. If *any* push event fires on a short interval (progress, status, logs), the renderer processes it, triggers React state change, re-renders.
- *Novelty:* Not a single leak — death by a thousand IPC paper cuts. Mac's IPC (Mach ports) has different cost profile than Linux Unix sockets.

**[H67] Renderer process receives logs it doesn't need**
- *Concept:* If main pipes server stdout/stderr to renderer for the log viewer, even when log viewer isn't open the renderer still processes events.
- *Novelty:* Need a "has log viewer mounted" gate before sending log frames.

**[H68] Electron's `RendererPaint` telemetry or built-in overhead**
- *Concept:* Newer Electron versions include telemetry paths unless explicitly opted out.
- *Novelty:* Low confidence but cheap to check (`app.commandLine.appendSwitch('disable-features', 'PaintHolding')` etc.)

**[H69] NativeWindow menu bar polling**
- *Concept:* `autoHideMenuBar: true` — menu bar state may poll.
- *Novelty:* Negligible; ruling out.

**[H70] Preload script runs heavy work on every mainWorld injection**
- *Concept:* If `preload.js` subscribes to many ipcRenderer channels, each message passes through preload validation.
- *Novelty:* Preload is a hot path on every IPC.

**[H71] Chromium's PaintHolding or throttling features disabled**
- *Concept:* Some `disable-features` switches are set (line 85-88 for Linux VAAPI). If `darwin` path accidentally disables a throttling feature, symptom appears Mac-only.
- *Novelty:* The Mac branch at `main.ts:90-94` only adds `MacLoopbackAudioForScreenShare,MacSckSystemAudioLoopbackOverride` — those shouldn't affect compositor. But worth confirming nothing else is toggled.

**[H72] WebContents devtools protocol attached**
- *Concept:* If any monitoring code attaches CDP, the renderer sends periodic telemetry.
- *Novelty:* Unlikely in prod.

**[H73] Electron's GPU process busy-loop**
- *Concept:* On Mac, Electron spawns a dedicated GPU process. If its event loop is busy (e.g., from compositor upload of large blur surfaces), it burns a whole core.
- *Novelty:* Reporter's screenshot shows total CPU 20%+ across app+helpers — this may be split between renderer + GPU helper. Check Activity Monitor per-process.

**[H74] Web workers or shared workers left running**
- *Concept:* None found in dashboard grep (Workers only in server side / tests). Ruling out.
- *Novelty:* Negative finding worth documenting.

**[H75] Main-process `child_process` spawn leaks**
- *Concept:* If `updateManager.ts` or any main-process module spawns a subprocess repeatedly (`ps`, `docker info`, etc.) without caching, each spawn is ~50 ms CPU on Mac.
- *Novelty:* `useDocker.ts` is the suspect entry point → main process does the actual Docker call.

### Domain I — Memory pressure / GC / allocations (ideas 76–80)

**[I76] AudioVisualizer per-frame Uint8Array allocation**
- *Concept:* Already noted in B11 but worth a dedicated entry: `new Uint8Array(analyserNode.fftSize)` inside `drawReal` (line 116) allocates every frame. At 60 Hz + fftSize ~2048 = 120 KB/sec of garbage.
- *Novelty:* Mac's ARC-ish JS heap compaction may be more noticeable than Linux's V8 on same hardware class.

**[I77] Template-literal className churn**
- *Concept:* Every render of every component with conditional classes allocates a new string. 500 components × 60 Hz (worst case if a top timer forces it) = thousands of short-lived strings/sec.
- *Novelty:* Individually microscopic; cumulatively GC pressure.

**[I78] Icon SVG re-render allocations**
- *Concept:* `lucide-react` returns JSX that allocates React elements tree on every render.
- *Novelty:* Correlates with re-render count from elsewhere.

**[I79] Closure leaks in useEffect callbacks**
- *Concept:* Effects that capture state and are re-registered on every render (missing stable deps) leave old closures pending until the next GC.
- *Novelty:* `useStarPopup`, `useAuthTokenSync` — audit deps.

**[I80] Dead reference holding from detached DOM nodes**
- *Concept:* If a React portal opens/closes repeatedly (modals) and the closing path doesn't clear event listeners, detached DOM accumulates.
- *Novelty:* Over hours, heap grows until GC has more to do.

### Domain J — Forced layout / reflow thrash (ideas 81–85)

**[J81] 21 layout-read call sites**
- *Concept:* `getBoundingClientRect`, `offsetWidth`, `offsetHeight`, `scrollTop` across 6 files. If any of these is called inside a rAF callback or a scroll handler without batching, it forces a synchronous layout before the read.
- *Novelty:* Common perf bug; Mac's paint pipeline is sensitive to layout thrash.

**[J82] SessionView scroll indicator recalculation**
- *Concept:* `SessionView.tsx:991,1025` — `requestAnimationFrame(recalcScrollIndicators)` likely reads `scrollTop/scrollHeight/clientHeight` then writes style. If it's called on every scroll tick (touchpad produces many), forced layout on every paint.
- *Novelty:* Directly plausible cause of scroll repaint artifacts.

**[J83] Sidebar `expandedWidthPx` state trigger**
- *Concept:* `Sidebar.tsx:67` stores `expandedWidthPx` in state. If it's recomputed from DOM measurement on every render, it's a feedback loop.
- *Novelty:* Low confidence without more context.

**[J84] ResizeObserver-driven layout re-reads**
- *Concept:* ResizeObserver callbacks are post-layout; safe. But if they write state that feeds back into size, it's a potential ping-pong.
- *Novelty:* Classic edge case; audit observer consumers.

**[J85] Canvas DPR resize on window.devicePixelRatio read**
- *Concept:* `AudioVisualizer.tsx:32-37` reads `window.devicePixelRatio` and resizes canvas. On ProMotion Mac, DPR can change (e.g. external monitor hotplug). If it re-fires resize, canvas reallocates.
- *Novelty:* Edge case; only if display config changes.

### Domain K — Accessibility / OS integration (ideas 86–90)

**[K86] VoiceOver / a11y tree rebuild on every DOM update**
- *Concept:* If VoiceOver (or similar) is enabled, macOS rebuilds the accessibility tree on every mutation. Our heavy re-render rate multiplied by that rebuild = real cost.
- *Novelty:* Ask the reporter whether VoiceOver or other a11y tools are on.

**[K87] Menu bar integration / dock badge**
- *Concept:* If we set dock badge or tray icon on state change, macOS animates.
- *Novelty:* Low confidence.

**[K88] Spotlight / Siri indexing of app window**
- *Concept:* macOS may index window titles/content. Not a Dashboard bug.
- *Novelty:* Ruling out.

**[K89] System Integrity Protection continuous checks**
- *Concept:* SIP for unsigned apps. Not our fault, but for ad-hoc builds possible.
- *Novelty:* Ruling out.

**[K90] Handoff / Universal Clipboard polling**
- *Concept:* Any app with focus may be polled by macOS for handoff state.
- *Novelty:* Ruling out.

### Domain L — User / config specific (ideas 91–95)

**[L91] Live Mode running silently (not disclosed)**
- *Concept:* Reporter says "live mode is not active" but did a previous live-mode session leave the recorder alive?
- *Novelty:* Ask for a "restart app and repeat" measurement.

**[L92] A model is still loaded / held in server**
- *Concept:* If the server backend is still holding a model in GPU VRAM, that's non-zero GPU use. Separate from Dashboard but could confuse the reporter's interpretation.
- *Novelty:* Reporter's chart shows "Idle (no transcription running, screen active)" — but the server may not be fully unloaded.

**[L93] Legacy GPU mode toggle state**
- *Concept:* Per memory, there's a CUDA-gated "legacy GPU" toggle. Irrelevant for Metal but check there's no cross-wired logic.
- *Novelty:* Unlikely.

**[L94] Config-file watcher rewriting / reloading constantly**
- *Concept:* If we watch config.yaml with chokidar-like, spurious reloads re-init components.
- *Novelty:* Worth auditing.

**[L95] Dashboard notebook auto-save timer**
- *Concept:* `useNotebookWatcher` / autosave writes may be frequent enough to cause render.
- *Novelty:* Tie to B16.

### Domain M — Wild / high-provocation (ideas 96–105)

**[M96] The flicker is a DPR mismatch between logical and backing store**
- *Concept:* If canvas `width` is set to `offsetWidth * dpr` but CSS sets logical pixels, a mismatch causes the browser to re-upload texture every frame.
- *Novelty:* Plausible edge case; can only reproduce on ProMotion.

**[M97] "Glass" blur triggers macOS's `NSVisualEffectView` accidentally**
- *Concept:* If the Electron window uses `vibrancy: 'under-window'` or similar native effect, the entire window background is blurred by macOS *on top of* the CSS blur.
- *Novelty:* Check `BrowserWindow` options for `vibrancy` / `transparent` / `backgroundMaterial`.

**[M98] The `backgroundColor: '#0f172a'` is never repainted but CSS overlays are**
- *Concept:* Our BrowserWindow opaque bg suggests we don't want transparency. Good — rules out vibrancy. But the CSS blur is still over an opaque bg.
- *Novelty:* Negative finding; reinforces A-domain.

**[M99] Model tab flicker is specifically z-index layer thrash**
- *Concept:* When entering Model tab, if parent container transitions `opacity`/`transform`, and children are `will-change`'d, compositor rebuilds the layer tree. For hundreds of items, rebuild + re-paint = visible flicker.
- *Novelty:* Explains tab-entry flicker specifically; other hypotheses don't.

**[M100] Tailwind JIT leaves unused style rules that still match**
- *Concept:* Generated CSS may have animation rules that match our elements accidentally, even though we didn't intend to animate them.
- *Novelty:* Check compiled CSS bundle for `@keyframes` count.

**[M101] Adversarial: "How would I intentionally make this worse?"**
- *Concept:* Reverse-brainstorming the reverse: add a `setInterval(() => forceUpdate(), 0)` in a hook. Has anyone done that accidentally? Audit `forceUpdate()` / `useReducer(x => x+1)` patterns.
- *Novelty:* Provocative audit — look for intentional-but-forgotten tick hooks.

**[M102] React DevTools / profiler left on in build**
- *Concept:* `__REACT_DEVTOOLS_GLOBAL_HOOK__` enabled increases render cost.
- *Novelty:* Check prod build for profiling.

**[M103] Canvas 2D context never destroyed on unmount**
- *Concept:* In `AudioVisualizer` cleanup, we `cancelAnimationFrame` but don't null the ctx or drop canvas. May be fine; cheap to inspect.
- *Novelty:* Minor.

**[M104] Provocation: assume the bug is NOT blur. What else explains all four symptoms?**
- *Concept:* Challenge: "What if blur is a red herring?" Alternative: a React re-render cascade triggered by UpdateBanner `nowTimer` → everything subscribing to a context re-renders → compositor is fine but JS is hot → still produces visibility-gated cost (rAF throttles hidden).
- *Novelty:* Forces us not to fixate. Test by temporarily disabling UpdateBanner entirely.

**[M105] Electron itself has a Mac-M4-Pro-Sequoia-specific regression**
- *Concept:* M4 Pro is brand new (Nov 2024). Apple silicon chip updates sometimes surface Chromium regressions. Check Electron GitHub for "M4" or "Sequoia" issues.
- *Novelty:* External cause — not our code. Rule out via version bump.

---

**Final Phase 1 tally: 105 hypotheses across 13 orthogonal domains.** Diminishing returns territory — the strongest leads remain [A1/B11], [A3-A5] blur stacking, [D31/D37/D39] Mac compositor behavior, and [E42/M99] model-tab-specific render-tree churn.

---

## Phase 2: Five Whys — Filter by "explains ALL four symptoms?"

### Observed symptoms (the test set)
- **S1:** High CPU in idle (when dashboard visible)
- **S2:** High GPU in idle (when dashboard visible)
- **S3:** Flicker on entering Model tab
- **S4:** Partial repaints / missing parts while scrolling
- **Boundary:** Usage drops when window is hidden or covered

A sufficient root cause should explain all four. A partial cause may only explain some; it can still contribute but isn't the primary.

### Cluster 1: AudioVisualizer always-on rAF loop (A1 / B11 / I76)

**Why #1 — Why does this exist?**
Component renders a live audio waveform. It needs rAF when audio is flowing.

**Why #2 — Why does it not stop in idle?**
`AudioVisualizer.tsx:134-141` calls `requestAnimationFrame(draw)` unconditionally. The `draw` function's only check is `if (analyserNode && freqData) { drawReal() } else { drawSimulation() }`. **No path cancels the rAF when `analyserNode` is null or when audio isn't flowing.** The rAF self-reschedules forever while mounted.

**Why #3 — Why does it produce both CPU and GPU load?**
- CPU: `drawSimulation` computes `Math.sin(…)` inside a `for (x = 0; x < width; x += 2)` loop for 3 layers per frame; `drawReal` iterates frequency bins and allocates a fresh `Uint8Array(fftSize)` per frame (line 116).
- GPU: `ctx.clearRect` + per-frame `beginPath/stroke/fill` on a Retina canvas submits a texture to Metal every frame. Metal counts that on the GPU meter.

**Why #4 — Why is it visibility-gated?**
Chromium throttles rAF to ~1 Hz on hidden renderer processes. When visible it runs at the display refresh rate (60 Hz or 120 Hz on ProMotion). So "visible" = full-speed loop; "hidden" = loop crawls.

**Why #5 — Does it explain Model-tab flicker and scroll artifacts?**
- **Model-tab flicker:** ❌ *No direct link.* The rAF loop runs at the same rate regardless of which tab is in view. However, it *may contribute* by pressuring the main thread whenever other work (React reconciliation) needs to run.
- **Scroll artifacts:** ❌ *No direct link.* Canvas paint doesn't block scroll.

**Verdict:** ✅ Fully explains S1, S2, and the visibility boundary. ❌ Does NOT explain S3, S4 directly (though may amplify them as a background load). **Necessary but not sufficient.**

---

### Cluster 2: Stacked backdrop-blur on ambient UI (A2 / A3 / A4 / A5 / D40)

**Why #1 — Why does it exist?**
Design language chose iOS-style "glass" aesthetic. Per `design-language.md`, blur is a primary surface treatment.

**Why #2 — Why does it burn GPU in idle?**
`backdrop-filter` forces Chromium to sample the pixels beneath each blurred element every frame the layer composites. Even with zero content change, if anything above the blurred layer is marked `will-change` or animated (see Tailwind `transition-*` classes), the composited frame is rebuilt.

**Why #3 — Why does it burn CPU?**
Compositor work is GPU-bound, but the driver still spends CPU on command-buffer encoding for Metal. On Retina (2× or 3× DPI) with `blur-xl` (24 px) or `blur-2xl` (40 px), command buffers are large — proportional CPU cost.

**Why #4 — Why is it visibility-gated?**
Chromium doesn't composite layers that aren't visible. Hidden window = no compositor work.

**Why #5 — Does it explain Model-tab flicker and scroll artifacts?**
- **Model-tab flicker:** ⚠️ *Partially.* Entering a tab that renders many `<GlassCard>` instances forces the compositor to allocate many new blurred layers. If layer count exceeds Chromium's budget on Mac (compositor layer pool), it may demote/re-promote layers — producing flicker.
- **Scroll artifacts:** ⚠️ *Partially.* During scroll, layers with `backdrop-filter` must re-sample the underlying content. If the compositor can't keep up, it can paint partial frames.

**Verdict:** ✅ Explains S1 (indirect), S2 (direct), visibility boundary. ⚠️ Plausible partial explanation for S3, S4. **Necessary; quite possibly sufficient when combined with Cluster 1.**

---

### Cluster 3: Mac-specific compositor amplification (D31 / D37 / D39 / D40)

**Why #1 — Why is this Mac-specific?**
Chromium's Mac backend uses Metal + CoreAnimation. `backdrop-filter` is implemented as a `CAFilter`. The work is real on all platforms but **the Mac GPU meter surfaces it clearly** while Linux/Windows surface it differently.

**Why #2 — Why M4 Pro specifically?**
ProMotion 120 Hz doubles the rate of rAF callbacks vs. 60 Hz displays.

**Why #3 — Why "visible even when partly covered"?**
NSWindow occlusion state only fires `.visible → .occluded` when the window is *fully* covered. If partially covered, Chromium still considers it visible → no throttling kicks in. This is the single most diagnostic piece of evidence in the issue thread.

**Why #4 — Why does it explain Mac vs. other platforms?**
Linux (X11/Wayland) and Windows have different occlusion semantics. Linux compositors may throttle more aggressively; Windows DWM similar.

**Why #5 — Does it explain Model-tab flicker and scroll artifacts?**
⚠️ *Not a root cause by itself.* It's an **amplifier** for any other cause. The platform characteristics mean any bad pattern in our code hurts more on Mac than on Linux.

**Verdict:** Not a root cause but a **critical multiplier**. Without this cluster, our code might still be wasteful but wouldn't be *noticeably* so. **Environmental — fix by reducing the cost of our code, not by "fixing" the platform.**

---

### Cluster 4: Model-tab render-tree churn (C22 / E42 / M99 / A4)

**Why #1 — Why does entering the Model tab flicker?**
`ModelManagerTab.tsx` iterates `MODEL_REGISTRY` and renders a `<GlassCard>` per model. Each GlassCard has `backdrop-blur-xl`. If the tab enters with a transition (opacity/transform) or if `refreshCacheStatus` fires on mount causing state change, the render tree churns during a GPU-expensive composite step.

**Why #2 — Why does GlassCard amplify the cost?**
Each GlassCard creates a composited layer (`backdrop-blur` promotes). Ten models = ten blurred layers in motion during tab transition. Compositor layer churn is visually visible as flicker.

**Why #3 — Why does it flicker rather than just "get slow"?**
Chromium's compositor has a layer budget. Exceeding it forces demotion of layers to the parent paint → layers "pop in" as they're re-promoted → reporter sees flicker.

**Why #4 — Why wouldn't this happen on Linux/Windows?**
The cost is the same but the threshold at which compositor visibly stutters is lower on Mac due to higher pixel count (Retina) and lower layer budget default (varies by GPU driver).

**Why #5 — Does it explain other symptoms?**
- S1/S2: Partial; tab-specific only. Doesn't explain idle on *other* tabs.
- S4 (scroll): Partial — scrolling the list of models stresses the same layer pool.

**Verdict:** ✅ Fully explains S3; partially explains S4. ❌ Does NOT explain S1/S2 when Model tab is *not* active. **Specific to one symptom cluster.**

---

### Cluster 5: Scroll-driven forced layout (J82 / C30 / A10)

**Why #1 — Why does scrolling produce repaints with missing parts?**
Per `SessionView.tsx:991,1025`, a `requestAnimationFrame(recalcScrollIndicators)` runs on scroll. If `recalcScrollIndicators` reads `scrollTop`/`scrollHeight` (layout-forcing) then writes inline styles, it creates a layout-paint cycle every frame of scrolling.

**Why #2 — Why "missing parts"?**
If the compositor is mid-paint when layout is invalidated, Chromium may composite a stale frame with some tiles not re-uploaded → visually: pieces missing.

**Why #3 — Why specifically on Mac?**
Retina's larger tile count + Metal's per-tile upload model means partial updates are more visually noticeable.

**Why #4 — Why not fire on other scroll events?**
Touchpads produce high-frequency scroll events. Mice produce fewer. Reporter on Mac → trackpad → many events.

**Why #5 — Does it explain idle CPU/GPU?**
❌ Only while scrolling, not idle.

**Verdict:** ✅ Fully explains S4. ❌ Does NOT explain S1/S2/S3. **Specific to scroll symptom.**

---

### Cluster 6: IPC / timer / re-render paper cuts (B12 / B13 / H66 / C21)

**Why #1 — Why does idle work happen at all?**
`UpdateBanner.tsx:401-403` runs `setInterval(() => setNow(Date.now()), NOW_TICK_MS)` every second. Plus 10s watchers (`useSessionWatcher`, `useNotebookWatcher`). Plus Docker poll. Plus auth token sync.

**Why #2 — Why does this cost real CPU?**
Each `setNow` re-renders the banner. If the banner's context leaks re-renders upward, children re-render. At 1 Hz × N children, React reconciles dozens/hundreds of elements.

**Why #3 — Why does it produce GPU load?**
A React re-render that touches `className` strings (even if resolved to identical output) forces Chromium to diff the style, possibly invalidating compositor layers. Repeated at 1 Hz, the compositor keeps working.

**Why #4 — Why is it visibility-gated?**
Chromium throttles `setInterval` callbacks for hidden renderer processes (5 min+ delay for long-hidden).

**Why #5 — Does it explain Model-tab flicker and scroll artifacts?**
- S3 (flicker): ❌ Not directly.
- S4 (scroll): ❌ Not directly.

**Verdict:** ✅ Explains S1, partially S2, visibility boundary. ❌ Does not explain S3/S4. **Necessary (low-level baseline); compounds with Clusters 1 & 2.**

---

### Synthesis — Which clusters are sufficient?

| Symptom | C1: AudioViz | C2: Blur stack | C3: Mac amp | C4: Model tab | C5: Scroll | C6: Paper cuts |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|
| **S1 CPU idle** | ✅ | ✅ | (mult) | partial | ❌ | ✅ |
| **S2 GPU idle** | ✅ | ✅ | (mult) | partial | ❌ | partial |
| **S3 Model flicker** | ❌ | ⚠️ | (mult) | ✅ | ❌ | ❌ |
| **S4 Scroll artifacts** | ❌ | ⚠️ | (mult) | partial | ✅ | ❌ |
| **Visibility gating** | ✅ | ✅ | — | ✅ | ✅ | ✅ |

**No single cluster explains all four symptoms.** The likely reality is **compound causation**:

- **Primary cause of S1+S2:** Cluster 1 (AudioVisualizer) + Cluster 2 (blur stack) running simultaneously, amplified by Cluster 3 (Mac platform).
- **Cause of S3:** Cluster 4 (Model-tab specific render churn + blur-layer count).
- **Cause of S4:** Cluster 5 (scroll-linked forced layout + compositor tile partial updates).

This means a full fix needs **three independent changes**, not one. That's an important conclusion for Phase 3.

### What Phase 2 rules out

- ❌ **"It's just blur effects"** as a single cause — doesn't explain S3/S4 cleanly.
- ❌ **"It's just the AudioVisualizer"** — explains idle cost but not tab/scroll symptoms.
- ❌ **"Platform-inherent, nothing we can do"** — Cluster 3 is a multiplier of *our* code's cost. Reducing the cost of Clusters 1, 2, 4, 5 reduces the amplified penalty.

### Hypotheses demoted or dismissed

- **[H66]** IPC paper cuts — reclassified as contributor, not driver (would not alone produce the scale reported).
- **[F-domain]** Build/env artifacts — likely ruled out by code inspection of the Metal build path; not high-value to pursue.
- **[K-domain]** Accessibility / OS integration — low prior, not pursued further unless reporter confirms a11y services running.
- **[M105]** Electron M4 Pro regression — still possible but not differentiating; subsumed into Cluster 3.

---

## Phase 2 — Round 2: Deeper Drilling

### Drill 2.1 — Careful re-read of the issue thread

Original text: _"I see the screen is heavily flickering when entering the model tab and screen is then redrawing constantly while scrolling with partially missing parts of **the list**."_

**The word "list" is load-bearing.** S4 is not generic scrolling — it is specifically **scrolling the model list on the Model tab**. This tightens the scope:

- S3 and S4 are the **same tab** (Model tab).
- S4's "list" is the `ModelManagerTab` rendered rows (one GlassCard per model).
- This collapses Clusters 4 and 5 for **S4 specifically** — the scroll-artifact symptom is not a general scroll bug; it is a symptom of too many composited blur-layers in a scrollable container on Mac.

**Implication:** Cluster 5 (generic scroll-linked forced layout in `SessionView`) may not even be active for this reporter at this time — they were on the Model tab, not the Session tab. C5's direct relevance to THIS issue drops substantially; it remains a latent bug, but not the one we're solving.

Second re-read: _"despite the fact there were only a few transcription runs of short audios... already has high cpu and gpu **times**"_

**The word "times" (plural) strongly suggests cumulative CPU time**, not instantaneous %. macOS Activity Monitor shows both "% CPU" (live) *and* "CPU Time" (cumulative since process started). Reporter's first screenshot (img 966×59 pixels) is likely a summary row showing accumulated time.

**Implication:** Reporter is complaining about **continuous idle work accumulating**, not necessarily spiky peak work. That favors a **constant low-to-moderate background loop** (rAF, 1Hz timers, continuous blur compositing) over a **one-off high spike**. This is exactly the AudioVisualizer + blur-compositing profile.

### Drill 2.2 — Interaction effects: do clusters compound additively or multiplicatively?

**Key finding:** The AudioVisualizer is mounted **inside a GlassCard** (`SessionView.tsx:1875` within `</GlassCard>` at 1879). `GlassCard` has `backdrop-blur-xl` (GlassCard.tsx:18).

Compositor implication:
- AudioVisualizer's canvas repaints every rAF tick (60 or 120 Hz).
- That repaint invalidates the content beneath the GlassCard's `backdrop-blur-xl`.
- Chromium must re-sample and re-blur that region on every frame.
- **This is multiplicative, not additive.** The canvas draw cost and the blur re-sample cost combine: every frame of canvas paint triggers a frame of blur re-sample over whatever area the GlassCard covers.

**Corollary:** C1 + C2 in isolation might each be moderate; *together*, they're the bulk of the idle cost. Fixing either one alone substantially reduces the *other* one's cost too. This is good news for Phase 3 — a partial fix has outsized returns.

**Second interaction:** UpdateBanner's `nowTimer` (C6) at 1 Hz forces a React re-render that may invalidate className strings. If those cascade to children with blur effects, the blur layers re-sample on every banner update. C6 × C2 is another multiplier.

### Drill 2.3 — Residual-cost predictions (if each cluster were disabled)

For Phase 3 planning, we need to predict what residual cost remains after each fix. All predictions static-analysis-based; none measured.

| Fix applied | Predicted residual CPU | Predicted residual GPU | Rationale |
|---|---|---|---|
| Disable AudioVisualizer only (stub to null) | 50–70% of baseline | 30–50% of baseline | Blur stack still invalidated by React re-renders; UpdateBanner timer still fires |
| Replace all `backdrop-blur-*` with opaque `bg-slate-*` only | 70–90% of baseline | 10–30% of baseline | AudioVisualizer still runs; React re-renders still cheap without compositor cost |
| Both of the above | 80–95% reduction → near-idle | 85–95% reduction | Dominant paths removed; only real-work paths (Docker poll, etc.) remain |
| Cluster 4 fix (memoize + virtualize Model list) | No change to S1/S2 | No change to S1/S2 | S3 only; idle cost is on other tabs too |
| Cluster 6 fix (rate-limit timers) | 5–15% reduction | Minimal direct change | Paper cuts; low individual impact |

**Key insight:** C1 and C2 fixes are the high-leverage moves. C4 fix solves a different symptom cluster (S3, S4 on Model tab). C6 is cleanup only.

### Drill 2.4 — Evidence gaps: what we don't know yet

We've been reasoning from code + one screenshot + three comments. The following would sharpen the diagnosis substantially:

1. **Instantaneous vs. cumulative CPU?** Reporter's screenshot could be either. Ask: "When the dashboard is visible and idle, what is the **% CPU** column (not CPU Time) in Activity Monitor for the TranscriptionSuite Helper (Renderer) process?"
2. **Per-process breakdown.** Electron runs ~4 processes (main, renderer, GPU, utility). Ask for each process's % CPU. If GPU helper is high → confirms compositor load (C2, C3). If renderer is high → confirms JS work (C1, C6). If both → both clusters active.
3. **ProMotion 120 Hz state.** System Settings → Displays → Refresh Rate. If 120 Hz → multiplies all rAF cost by 2×.
4. **Plugged in vs. battery.** M-series Macs throttle on battery; plugged-in runs at full boost.
5. **Tab-specific measurement.** Does the Dashboard's idle cost depend on which tab is open? If Session tab (which has AudioVisualizer) > Model tab > Settings tab → AudioVisualizer confirmed. If all tabs same → something else.
6. **AudioVisualizer null-analyser path.** Is `analyserNode` null while idle (no recording)? Then the sine-wave simulation is running. If the simulation is running continuously, the waveform is visibly animated even when not recording. **The reporter could just look at the Session tab and say yes/no.**
7. **Server running state.** Is the Python server process alive? It could be holding a model. "No transcription running" ≠ "no server".
8. **Repro on clean account.** Does a fresh macOS user account (with no other apps installed) reproduce? Rules out third-party interference.

### Drill 2.5 — Adversarial self-review: "What if we're wrong about all 6 clusters?"

Stress-testing our hypothesis set.

**Challenge 1 — What if the issue is server-side (Python), not Dashboard?**
- Reporter opened the app "yesterday" and ran short transcriptions. If the model is still loaded in server memory, the Python process may still be doing some work (GC, HF hub checks, etc.). Mac M4 Pro has a unified memory architecture, so server RAM pressure affects the display subsystem's memory budget.
- **But:** the reporter says usage drops when the **window is covered**. Server doesn't care about window visibility. So server activity can't explain the visibility gating. Ruling out.

**Challenge 2 — What if it's the Electron main process, not the renderer?**
- `electron/main.ts:94 IPC handlers` means main is reachable from renderer. But main-process CPU shows as a separate process in Activity Monitor. Reporter would see "TranscriptionSuite" (main) and "TranscriptionSuite Helper (Renderer)" separately.
- If main is hot and the others are cool → our clusters are wrong, look at `updateManager.ts` and `appState.ts` timers.
- If renderer is hot → our clusters are right.
- This is why per-process breakdown is in the evidence gap list.

**Challenge 3 — What if the reporter has dev tools open?**
- DevTools themselves consume significant CPU/GPU. If the reporter accidentally opened them (Cmd+Alt+I), that's the whole explanation.
- Mitigation: `electron/main.ts:758` says "Block all DevTools entry points in production" — likely fine, but worth confirming the block is complete.

**Challenge 4 — What if it's a third-party macOS app polling us?**
- Some Mac apps (window managers, clipboard managers, accessibility tools) continuously read DOM / accessibility state.
- The visibility gating signal *kind of* still fits this if the third-party polls only visible windows — but that's a very specific behavior. Low prior.

**Challenge 5 — What if it's a font or asset that's loading continuously?**
- If a webfont is being re-fetched (cache header broken), network I/O continues. But that wouldn't peg the GPU.

**Challenge 6 — What if we're miscategorizing the "GPU" signal?**
- Reporter's "GPU time" could be Activity Monitor's "Energy → GPU" which includes any Metal command buffer, including tiny ones. If our app submits any work to Metal even every second, GPU time accumulates.
- **But this doesn't let us off the hook** — it means the metric is sensitive, and our continuous compositing is surfaced clearly.

**Challenge 7 — What if the flicker on Model tab is caused by the *tab transition itself*, not the Model tab's content?**
- Tab transitions likely use `opacity` or `translate` on a container. If the transition forces layer re-creation for the entering tab's contents, and entering contents are many blurred cards, flicker matches.
- This is actually reinforcement for Cluster 4 (layer pool churn).

**Conclusion of adversarial review:** No cluster is falsified; per-process evidence gap (Drill 2.4 #2) is the single most important gap to close because it distinguishes "renderer-hot" from "main-hot" clusters.

### Drill 2.6 — Why this bug survived into production

A Five Whys on the *absence of detection*:

1. **Why wasn't this caught in dev?** — Dev env is Linux KDE Wayland (per project notes).
2. **Why does Linux hide the symptom?** — Linux compositors throttle occluded windows more aggressively, and don't surface per-frame GPU use as a visible metric in casual monitoring.
3. **Why wasn't it caught in CI?** — CI runs unit tests (`pytest` / `vitest`), not runtime perf measurements. No idle-state benchmark exists.
4. **Why wasn't there a cross-platform perf check?** — Mac CI exists for build verification (`.github/workflows/`), but builds are artifact checks, not runtime.
5. **Why don't our design patterns flag this class of bug?** — `design-language.md` *does* warn about blur stacking, but the warning isn't enforced. We have a `ui-contract` system — it could grow a "blur-depth budget" rule.

**Actionable consequence:** the fix shouldn't stop at the immediate bug. A regression guard is cheap: a Playwright-driven idle-state CPU measurement on the Mac CI runner, or a static check in `ui-contract` that fails when total `backdrop-blur` depth exceeds a budget.

### Drill 2.7 — Revised symptom map

Now that "the list" means "the model list", the map tightens:

| Symptom | Primary mechanism | Secondary / amplifier |
|---|---|---|
| S1 CPU idle (any tab) | AudioVisualizer rAF (C1), compound with C2 | C6 timer re-renders |
| S2 GPU idle (any tab) | Blur stack re-sampled by C1 canvas paint | C3 Mac amplifier |
| S3 Model tab flicker | Layer-pool churn on tab transition × many GlassCards (C4) | C3 amplifier |
| S4 Model list scroll | Same C4 cause — many blur layers × scroll invalidation | C3 amplifier |

**S3 and S4 now collapse into one cluster (C4 on the Model tab). S1/S2 is a joint C1+C2 multiplicative effect.** The problem is now **two clusters**, not three.

### Drill 2.8 — Simplest-possible-fix prediction

If I had to ship one patch today without any Mac access:
1. **Gate AudioVisualizer's rAF on an `isActive` prop** that defaults to false; only the Session tab's recording path should set it true. When false, return early / don't schedule the next frame. (C1)
2. **Memoize the per-row GlassCard in `ModelManagerTab`** with `React.memo` and stable deps, and consider `virtualized` list if model count is > 20. (C4)
3. **Audit blur stacking** per `design-language.md:61` — ship a contract rule capping `backdrop-blur` depth to 1 nested layer. (C2 prevention)

These three changes likely drop the reporter's numbers by 70–90% without needing a single Mac test to write them. Empirical confirmation then comes from the reporter running the patched build.

---

## Phase 3: Solution Matrix

Each row is a hypothesis or cluster. Columns score it on dimensions relevant given the "no Mac" constraint.

**Scoring keys:**
- **Likelihood:** High / Med / Low / Negligible — probability this is a real contributor
- **Static-confirmable:** ✅ confirmable from code reading alone / ⚠️ partial / ❌ needs Mac
- **Evidence needed:** What, if anything, the reporter must provide to confirm
- **Fix effort:** S (<1 hr), M (few hrs), L (day+), XL (multi-day + test infra)
- **Impact if fixed:** estimated % reduction in reporter's idle CPU+GPU
- **Shippable risk:** Low / Med / High — risk that the fix could break existing behavior
- **Regression-guard feasible:** can we add a static/runtime check to prevent recurrence?

### Core idle-cost cluster (S1 + S2)

| ID | Hypothesis | Likelihood | Static-confirmable | Evidence needed | Fix effort | Impact if fixed | Ship risk | Reg-guard |
|----|---|---|---|---|---|---|---|---|
| **C1** | AudioVisualizer rAF runs without isActive gate | High (confirmed by code read) | ✅ | Tab-specific measurement from reporter (optional; already very high confidence) | S | 40–60% | Low (early return on false) | ✅ lint rule: canvas-based viz requires active prop |
| **C1-sub** | Per-frame `new Uint8Array(fftSize)` allocation | Med | ✅ | none | S | 5–10% | Low | ✅ lint rule: no allocation in rAF |
| **C2-a** | GlassCard wraps AudioVisualizer → blur × canvas multiplication | High (confirmed SessionView.tsx:1875) | ✅ | none | S | subsumed by C1 fix | Low | — |
| **C2-b** | Stacked backdrop-blur across 21 files, 36 call sites, some nested | High (partially confirmed; full audit needed) | ⚠️ need full audit | none if audit done | M | 20–40% | Med (visual design change) | ✅ ui-contract blur-depth budget |
| **C6** | UpdateBanner `nowTimer` 1Hz re-render | Med | ✅ | none | S | 5–15% | Low (reduce tick to on-demand) | ✅ lint rule: setInterval must justify freq |
| **H66** | IPC paper cuts from 94 handlers | Low-Med (not driver; contributor) | ⚠️ | per-process CPU breakdown | L (requires IPC audit) | 5–10% | Med | ⚠️ hard to automate |

### Model-tab cluster (S3 + S4, now unified)

| ID | Hypothesis | Likelihood | Static-confirmable | Evidence needed | Fix effort | Impact if fixed | Ship risk | Reg-guard |
|----|---|---|---|---|---|---|---|---|
| **C4-a** | Many GlassCards (each with backdrop-blur) in scrollable list → layer-pool churn | High | ✅ | none | M | Fully fixes S3/S4 | Low | ✅ ui-contract: list-item blur budget |
| **C4-b** | Not memoized → parent re-renders rebuild all rows | Med | ⚠️ need code read of ModelManagerTab in full | none | S | Contributes to S3 | Low | ✅ eslint rule: React.memo on list items with N>10 |
| **C4-c** | No virtualization | Med (depends on model count) | ✅ | how many models? | M–L | S3/S4 mitigation at scale | Med | — |
| **E42** | `refreshCacheStatus` fires on tab mount → state change cascade | Low-Med | ⚠️ | none (static review) | S | 5–10% | Low | — |

### Mac platform amplifier (environmental — cannot "fix", but can mitigate)

| ID | Hypothesis | Likelihood | Static-confirmable | Evidence needed | Fix effort | Impact if fixed | Ship risk | Reg-guard |
|----|---|---|---|---|---|---|---|---|
| **C3** | Mac Metal + Retina × DPI + NSWindow occlusion behavior | Confirmed (platform characteristic) | N/A | — | N/A (environmental) | N/A | N/A | ❌ |
| **D39** | NSWindow occlusion only fires when fully hidden | Confirmed (platform) | N/A | reporter can verify "fully vs partly hidden" test | N/A | — | — | — |
| **D37** | ProMotion 120 Hz doubles rAF rate | Med | N/A | reporter's refresh-rate setting | N/A | Mitigated by C1 fix | — | — |
| **M105** | Electron version has M4 Pro / Sequoia regression | Low-Med | ✅ (check package.json + issue tracker) | Electron version number | L (version bump) | Variable | Med (regression risk) | — |

### Ruled out / deprioritized

| ID | Hypothesis | Reason for deprioritization |
|---|---|---|
| F-domain | Build/env artifacts (devtools, HMR, sourcemaps) | Main.ts hardening already present; low prior |
| K-domain | Accessibility / OS integration | Requires specific user setup; low prior |
| L91 | Live Mode running silently | Already handled by existing lifecycle |
| Challenge-1 | Server-side Python process | Ruled out by visibility gating |
| Challenge-4 | Third-party macOS app polling | Low prior; not actionable from our side |
| C5 (SessionView scroll indicators) | Not active on reported (Model) tab | Latent bug, not this bug |

### Matrix summary — ranked by (Impact × Static-confirmable) / Effort

| Rank | Action | Impact | Effort | Why |
|---|---|---|---|---|
| 1 | Add `isActive` gate to AudioVisualizer rAF (C1) | 40–60% | S | Highest leverage, trivial code change, near-zero ship risk |
| 2 | Audit + dedup backdrop-blur layers (C2-b) | 20–40% | M | Design-language doc already warns; just enforce |
| 3 | Memoize ModelManagerTab rows (C4-b) | Fixes S3/S4 partial | S | Quick win, no design change |
| 4 | Tune UpdateBanner `nowTimer` to on-demand (C6) | 5–15% | S | Cheap; doesn't need to tick if no snooze active |
| 5 | Add virtualization to model list if > 20 (C4-c) | S3/S4 scale guard | M | Future-proofs as registry grows |
| 6 | Add `ui-contract` blur-depth budget (regression guard) | Prevention | M | Aligns with existing contract system |
| 7 | Playwright-on-Mac idle CPU measurement (regression guard) | Prevention | L | Catches this bug class in CI |
| 8 | Electron version audit against M4 known-issues (M105) | Variable | L | Only if #1–#3 don't fully resolve |

**Key takeaway:** the first three actions are all **code-only, static-confirmable, and shippable without Mac access**. They can be implemented and merged; the reporter confirms the fix by running the released build. This is the rare RCA where "no Mac available" actually doesn't block progress.

---

## Phase 4: Decision Tree — Diagnostic triage for the Mac reporter

Minimum-effort diagnostic script to confirm/rule out clusters. Designed so the reporter (or @twilsonco if available) can paste findings into the issue. Each step is ordered by information-per-effort.

### Step 1 — Baseline + per-process breakdown (the single most informative step)

**Reporter action (5 minutes):**
1. Quit TranscriptionSuite completely.
2. Open Activity Monitor → View → Dock Icon → "Show CPU Usage".
3. Launch TranscriptionSuite, do NOT start any transcription. Wait 60 seconds for warm-up.
4. In Activity Monitor, find processes containing "TranscriptionSuite":
   - `TranscriptionSuite` (main)
   - `TranscriptionSuite Helper (Renderer)`
   - `TranscriptionSuite Helper (GPU)`
   - `TranscriptionSuite Helper (Plugin)` if present
5. Report the **% CPU** (not CPU Time) for each, with the app window **fully visible**.
6. Minimize or cover the window completely, wait 30 seconds, report again.

**Decision:**

| Visible CPU pattern | Hidden CPU pattern | → Indicates |
|---|---|---|
| Renderer high (> 5%) | Renderer drops to ~0 | Cluster 1 (AudioViz rAF) and/or Cluster 6 (timers) |
| GPU helper high (> 3%) | GPU helper drops | Cluster 2 (blur compositing) |
| Both renderer + GPU high | Both drop | C1 × C2 multiplicative (expected primary cause) |
| Main high, renderer low | Main drops | Uncommon — points at Electron main-process timers |
| All low (<2% each) | — | Reporter's concern may be about cumulative CPU Time, not live % |

### Step 2 — Zero-cost visual test (confirms C1 in seconds)

**Reporter action (30 seconds):**
- Open the Session tab (the default view with transcription UI).
- Without starting any recording, observe the audio visualizer area.
- **Is the cyan/magenta/orange sine wave visibly animating?**

**Decision:**
- **Yes, animated:** Confirms C1 (AudioVisualizer rAF running in null-analyser simulation mode). Ship fix #1 from the Matrix.
- **No, static:** C1 is not primary; look at C2 more heavily.

### Step 3 — Tab-specific measurement

**Reporter action (3 minutes):**
- In Activity Monitor, watch Renderer % CPU.
- Click through tabs in this order, waiting 20 s each:
  1. Session tab
  2. Model tab
  3. Settings (or any tab without AudioVisualizer)
- Note the % CPU on each.

**Decision:**
- **Session tab noticeably higher than other tabs:** Confirms C1.
- **All tabs similar:** C1 is not tab-dependent (unexpected; may indicate AudioViz mounted elsewhere or different root cause).
- **Model tab higher than Session:** C4 is dominant; reconsider priorities.

### Step 4 — ProMotion refresh-rate check (quick environmental datum)

**Reporter action (30 seconds):**
- System Settings → Displays → "Refresh Rate".
- Note the setting: ProMotion / 120 Hz / 60 Hz / etc.

**Decision:**
- **ProMotion or 120 Hz:** All rAF loops doubled; amplifies our code's cost. Explicitly confirms D37.
- **60 Hz:** No ProMotion multiplier; reporter's numbers reflect 60 Hz baseline.

### Step 5 — Window-cover test (confirms C3/D39 exact semantics)

**Reporter action (2 minutes):**
- Observe CPU % while:
  1. App visible, window focused.
  2. App visible but another app's window covers it **partially** (e.g. 90% covered, 10% still peeking).
  3. App fully covered by another window.
  4. App minimized to dock.

**Decision:**
- **Drops between 2 and 3 (partial → full cover):** Confirms D39 (NSWindow occlusion only fires on full cover). Validates environmental amplifier model.
- **Drops between 1 and 2 (focused → partial cover):** Throttling fires earlier; our model needs revision.

### Step 6 — Patched-build verification (after fix ships)

**Reporter action (same as Steps 1–3 but on the patched build):**
- Compare before/after numbers.
- Target: Renderer < 2% idle, GPU helper < 1% idle, no visible flicker on Model tab.

**Success criteria:**
- S1 CPU idle reduced by ≥ 70%.
- S2 GPU idle reduced by ≥ 70%.
- S3 flicker gone or only momentary.
- S4 scroll artifacts gone.

If not met: escalate to Step 7.

### Step 7 — Escalation (if Steps 1–3 show unexpected patterns)

If the fix doesn't land the target:
- Revisit adversarial challenges 2 and 4 (main-process hot, third-party app polling).
- Request Electron version number → check against known M4 Pro / Sequoia regressions (M105).
- Consider Chrome DevTools Performance profile from reporter: `electron --inspect` or "Open DevTools" on a dev build. Expensive for reporter, last resort.

---

## Session Summary

**Methodology:** Progressive Technique Flow with four phases — Reverse Brainstorming (105 hypotheses, 13 domains, anti-bias pivot every 10), Five Whys (6 clusters filtered by "explains all four symptoms?"), Solution Matrix (scored on impact / effort / static-confirmability given no-Mac constraint), Decision Tree (diagnostic triage for reporter).

**Conclusion:** Two cluster causation.
- **Cluster A (S1+S2 idle CPU/GPU):** AudioVisualizer rAF runs without isActive gate (`AudioVisualizer.tsx:134-141`), mounted inside a `<GlassCard>` with `backdrop-blur-xl`. Canvas paint × blur re-sample is multiplicative. Platform amplifier = Mac Metal + Retina DPI + NSWindow occlusion semantics.
- **Cluster B (S3+S4 Model tab flicker + scroll artifacts):** Many backdrop-blurred `<GlassCard>` rows in scrollable `<ModelManagerTab>` list exceed Chromium's Mac compositor layer budget, causing visible layer demotion/re-promotion flicker and partial tile updates during scroll.

**Three-change fix (no Mac needed to write):**
1. Gate `AudioVisualizer` rAF on `isActive` prop — only run when recording.
2. `React.memo` + stable keys on `ModelManagerTab` rows; virtualize if > 20 models.
3. `ui-contract` blur-depth budget rule (enforces what `design-language.md:61` already warns about).

**Predicted fix impact:** 70–90% idle CPU/GPU reduction for the reporter.

**Verification path:** reporter runs Steps 1–3 of the diagnostic tree on patched build.

**Regression guard:** Playwright-on-Mac idle-CPU benchmark in CI + `ui-contract` blur-depth rule.

**Ideas generated:** 105.
**Techniques used:** Reverse Brainstorming, Five Whys, Solution Matrix, Decision Tree Mapping.

### Creative Facilitation Narrative

Session adapted standard creative brainstorming techniques for a technical RCA use case: the "creative quantity" phase became "hypothesis enumeration with anti-bias domain pivoting"; the "pattern recognition" phase became the symptom-sufficiency filter; the "idea development" phase became feasibility scoring under the "no Mac" constraint; the "action planning" phase became a diagnostic decision tree for the reporter. The LLM acted as primary generator (given user's auto-mode preference and stated lack of target hardware); the user steered through approach selection and continuation choices.

The session's most valuable moment was Phase 2 Round 2's careful re-read of the issue text ("the list" = model list), which collapsed what appeared to be three symptom clusters into two. This is a pattern worth carrying forward: in any RCA, the primary source material is the reporter's exact words; re-reading for load-bearing terms should be a standard phase.

### Session Highlights

**Breakthrough moments:**
- Discovery that `AudioVisualizer` rAF has no isActive gate AND is unconditionally mounted in `SessionView`.
- Recognition that the visualizer canvas sits *inside* a `<GlassCard>` with `backdrop-blur-xl` — making C1 and C2 multiplicative.
- Re-reading "the list" to mean the model list, collapsing S3 and S4 into one cluster.
- Insight that the three top fixes are all code-only and shippable without Mac access — rare for a platform-specific bug.

**Decisions for next session (implementation):** Use this session's Phase 3 ranking as the implementation order. Start with AudioVisualizer `isActive` gate (fix #1) as a standalone PR — maximum leverage, minimum ship risk.

---

# Extension — Blur GPU Cost Reduction (2026-04-25)

**Continuation rationale:** Of the three top fixes from the original RCA, two shipped as actual cost reductions (commits `048dba8` AudioVisualizer rAF gate, `66473b4` ModelManager memo + content-visibility). The third — Cluster C2-b "Audit + dedup backdrop-blur layers" — shipped only as a regression *guardrail* (commit `97c525d` ui-contract blur-depth budget rule, with grandfathered per-file overrides). The actual cost reduction is still ahead of us. This extension session brainstorms how to attack it without abandoning the iOS-glass design language.

**New phase scope:** Reduce GPU cost of `backdrop-filter` / `backdrop-blur` across the dashboard while preserving the glass aesthetic. Predicted impact ceiling = 20–40% (per C2-b in Phase 3 matrix); target is ship-ready ideas with explicit aesthetic-cost tradeoffs.

**Hard inputs:**
- 21 files / 36 call sites of `backdrop-blur` in `dashboard/`
- Per-file budgets (grandfathered): `App.tsx=8`, `AudioNoteModal=5`, `BugReportModal/NotebookView/ServerSettingsModal/SessionView=4`, default=3
- Hot files: `GlassCard.tsx`, `Sidebar.tsx`, `NotebookView.tsx`, `FullscreenVisualizer.tsx`, modals (`SettingsModal`, `AboutModal`, `UpdateModal`, `AudioNoteModal`, `BugReportModal`, `AddNoteModal`, `StarPopupModal`)
- AudioViz × GlassCard multiplicative interaction is already neutralized (rAF gate)
- Mac Metal + Retina is the worst amplifier; Linux/Windows also pay

**Out of scope:** AudioVisualizer rAF (shipped), ModelManager memo (shipped), ui-contract budget enforcement (shipped), Cluster 6 timer/IPC paper cuts (separate thread).

---

## Phase 1 — Expansive Exploration (Morphological + SCAMPER hybrid)

**Goal:** ≥ 100 ideas across orthogonal domains. Force-pivot every 10 ideas. Anti-bias rule: ban two consecutive radius-reduction ideas.

### Domain D1 — Trigger conditions (when does blur actually run?)

**[E1] `content-visibility: auto` on every blurred container**
- Already used on ModelManager rows in commit `66473b4`. Expand to every `GlassCard` and every modal's blurred shell.
- Mechanism: Chromium skips paint *and* the underlying behind-blur sample for off-screen content.

**[E2] IntersectionObserver-driven blur class toggle**
- Strip `backdrop-blur-*` class when card scrolls fully out, restore on intersection.
- Distinct from E1: applies even when `content-visibility` doesn't (e.g. partial-visibility cards in long lists).

**[E3] Pause blur during scroll**
- On `scroll`, set `data-scrolling="true"`; CSS rule `[data-scrolling="true"] .glass { backdrop-filter: none }`. Restore on `scrollend`.
- Trade: brief opaque flash during scroll, but eliminates the worst-case scroll repaint cost (matches reporter's S4 symptom).

**[E4] Drop blur on window-blur**
- When the BrowserWindow loses focus, swap to opaque variant. AudioViz is already gated on `isActive`; do same for visual chrome.
- Aligns with macOS HIG: inactive windows have reduced visual fidelity natively.

**[E5] Battery-aware downgrade**
- `navigator.getBattery().then(b => document.documentElement.dataset.power = b.charging ? 'plug' : 'batt')`. CSS halves radius on `[data-power="batt"]`.
- M-series Macs throttle GPU on battery; aligns blur cost with available headroom.

**[E6] `prefers-reduced-motion` strips blur**
- Already an accessibility setting users opt into for "fewer effects." Treat blur as motion-adjacent.
- Free credibility win; matches OS-level user intent.

**[E7] DevTools-open detection kill-switch**
- Electron can detect devtools attach; emit a `data-devtools="true"` flag → CSS strips blur.
- DevTools already wrecks perf; freeing GPU for the user fixing a bug is courtesy.

**[E8] `document.visibilityState === 'hidden'` strips blur layers entirely**
- Page Visibility API. NSWindow occlusion (Drill 2.4 #2) only fires on full cover; this is JS-side belt + suspenders.

**[E9] Render-tree-anchored gating: `[data-active="true"] .glass`**
- Routes/tabs declare which surface is "active"; blur applies only to active subtree.
- Forces explicit ownership of glass surfaces — no incidental blur in inactive views.

**[E10] Performance-pressure auto-downgrade**
- Sample `performance.now()` rAF jank; if 3 frames > 33ms in a row, set `--glass-fidelity: 0.5`.
- Self-healing — Mac users automatically get the cheap variant when their system is loaded.

*[PIVOT — domain change]*

### Domain D2 — Radius (anti-bias: max one consecutive radius idea)

**[E11] Single CSS variable `--blur-radius-xl: 24px`**
- Currently `backdrop-blur-xl` is hardcoded at 24px by Tailwind. A token lets us tune per-platform/tier without touching components.
- Foundation for E12, E94, E95.

*[pivot]*

**[E12] (non-radius) Layer flattening: collapse nested blurs into single parent blur**
- `NotebookView.tsx:725,727` has `backdrop-blur-xl` + `backdrop-blur-md` nested. Flatten to single tier on parent.
- Identifier `A3` from RCA: explicitly warned against in `design-language.md:61` but still present.

**[E13] Quantize radius to 4px steps {0,4,8,12,16,24}**
- Chromium can cache shaders for common radii. Random radii (e.g. `blur-[18px]` arbitrary values) defeat shader cache.
- Cheap correctness win even if no surface changes.

*[pivot]*

**[E14] Replace `backdrop-blur-3xl` (FullscreenVisualizer:50) with `backdrop-blur-xl + brightness(0.6)`**
- Perceptually similar at 1/3 the kernel size. The `-3xl` (64px) is a high-radius convolution; `xl` (24px) is dramatically cheaper.
- Single-line change; FullscreenVisualizer is a transient overlay so risk is low.

**[E15] (non-radius) Half-resolution blur via offscreen canvas**
- Render blurred surface to a 0.5× canvas, scale up with bilinear filtering. Halves the blur kernel pixel count.
- Implementation cost: medium. Quality cost: minor edge softness.

*[pivot]*

**[E16] CSS `clamp(8px, 2vw, 24px)` viewport-adaptive radius**
- Small windows (sidebar collapsed, dashboard floated narrow) get smaller radii.
- Naturally scales cost with rendered area.

**[E17] (non-radius) Rounded-corner clipping reduces blurred pixel count**
- `border-radius: 24px` on a blurred surface forces extra clipping passes in Chromium. Audit components: do all GlassCards need rounded corners? Some can be square-cut.

**[E18] Per-tier radius taxonomy**
- T1=24px (modals, hero), T2=12px (cards), T3=4px (sidebar/header ambient), T4=0px (decorative scroll edges).
- Currently every surface uses the same `xl` token. A tier system encodes "this surface gets the expensive treatment, that one doesn't."

**[E19] (non-radius) `backdrop-saturate(1.5)` instead of blur on T3 surfaces**
- Saturation alone often reads as "frosted." Cheap filter; no kernel sampling required.
- Test: on Sidebar.tsx:219, swap `backdrop-blur-2xl` for `backdrop-saturate-150`. Compare visually.

**[E20] (non-radius) `filter: blur()` on a sibling pseudo-element**
- `::before` with the inherited background image and `filter: blur()` is sometimes cheaper than `backdrop-filter` on the same element, because the browser paints the pseudo once and re-uses.

*[PIVOT]*

### Domain D3 — Layer depth / nesting

**[E21] Single-blur surface architecture**
- Hoist all blur to one root parent layer; children become `bg-white/10` opaque-on-glass.
- Eliminates the "multiplicative" cluster: instead of N blurred layers, one.

**[E22] NotebookView: collapse nested blur (lines 725, 727)**
- `backdrop-blur-xl` on container + `backdrop-blur-md` on header → keep header tier, drop container tier (or vice versa).
- Direct fix to A3 from RCA.

**[E23] Modal-on-glass-on-glass: parent blur OFF when modal opens**
- When `SettingsModal` opens, the parent view's `backdrop-blur` is invisible behind it anyway. Strip parent blur on `modal-open` event.
- Mechanism: CSS `[data-modal-open] .view-glass { backdrop-filter: none }`.

**[E24] Sibling-blur pattern**
- Render glass background as a separate `position: absolute; inset: 0; pointer-events: none` sibling. Children render in normal flow without forcing blur context re-promotion.
- Decouples blur from layout/transition costs on children.

**[E25] App.tsx blur=8 audit**
- `App.tsx` has 8 grandfathered blur uses (highest in the project). Map each to {nested, independent}. Flatten the nested ones.
- Each flatten = one less compositor layer.

**[E26] Native `<dialog>` `::backdrop` pseudo-element**
- HTML `<dialog>` element has a free `::backdrop`. Use it for modal scrim + blur instead of an extra blurred React div.
- Bonus: better a11y, free Esc-to-close.

**[E27] Portal-mount modals to `document.body`**
- Modals inheriting parent blur context create stacking-context tangles. Portaling resets the context.
- React.createPortal — already supported.

**[E28] `isolation: isolate` on modal root**
- Forces a new stacking context, may let Chromium short-circuit behind-blur sampling outside the isolate region.
- One CSS line per modal; experimentally test impact.

**[E29] Box-shadow + tint instead of nested blur**
- `box-shadow: inset 0 1px 0 rgba(255,255,255,0.1)` plus `bg-white/8` simulates layered glass without a second blur pass.

**[E30] Detect & fail nested blur in ui-contract**
- New contract rule: "no `backdrop-blur` descendant of another `backdrop-blur`." Currently the budget allows any depth; this detects stacks specifically.
- Enforcement complement to E22, E25.

*[PIVOT]*

### Domain D4 — Spatial extent (how big is the blurred area?)

**[E31] Confine blur to chrome regions only**
- Sidebar, header, footer, modals get blur. Content surfaces (Session main, Notebook body, Model list) become opaque.
- Aggressive but explicit: blur is for chrome, not content.

**[E32] Frosted-edge: 1px ring of blur, opaque interior**
- `<div class="glass">` becomes a thin border with `backdrop-filter` and an interior solid color. Preserves "glass" perception at ~5% pixel cost.
- Implementation: `::before` with `inset: 0; border: 1px solid; backdrop-filter: blur(12px)`.

**[E33] Viewport clip-path on blur**
- `clip-path: inset(0 0 0 0)` driven by IntersectionObserver — only the on-screen portion of a long blurred element is sampled.
- Specifically helps when a blurred Sidebar extends past the viewport.

**[E34] Sidebar.tsx:219 — restrict blur to top 80px (header zone)**
- Currently `backdrop-blur-2xl` on full-height. Most of the sidebar's blurred area is below the fold or behind opaque buttons.
- Reduces blurred pixels by ~80% on tall windows.

**[E35] Modal blur clipped to bounding box, not full-screen scrim**
- Currently modals usually have a full-screen blurred backdrop. Replace scrim's blur with `bg-black/40` opaque scrim; blur only the modal panel itself.

**[E36] SessionView scroll-edge fades (4 sites): drop blur, keep gradient**
- Lines 1174, 1774, 1799, 2279 use `bg-linear-to-* + backdrop-blur-sm`. The gradient alone produces the visual; the `-sm` blur is decorative.
- Identifier `A8`/`A10` from RCA. Free fix.

**[E37] AudioNoteModal: blur header strip, opaque body**
- AudioNoteModal has 5 grandfathered blurs (high). Most could be tier-flattened. The header strip carries the visual identity; body can be solid.

**[E38] NotebookView: blur only when scrolled past header**
- IntersectionObserver on header sentinel → toggle blur class on body. At-top = opaque, scrolled = blurred (sticky-header glass).
- Common iOS pattern; matches user mental model.

**[E39] NotebookView main surface: tiled noise texture instead of blur**
- A 64×64 tiled PNG with subtle noise + tint reads as "frosted" without sampling.
- Static asset, 0 ongoing GPU.

**[E40] FullscreenVisualizer: donut clip-path**
- Blur the area *outside* the visualizer canvas region (decorative aura), not under the canvas.
- Canvas is opaque anyway — backdrop-blur underneath it does nothing visible.

*[PIVOT]*

### Domain D5 — Update frequency / staleness

**[E41] Snapshot-blur: render once, cache as `<canvas>` background**
- On tab activate, render the blurred surface once via `html2canvas` or `OffscreenCanvas`, set as `background-image`. No `backdrop-filter`.
- Invalidate on resize/scroll/content change.

**[E42] Static-content marker: `data-content-static="true"`**
- Surfaces declare "nothing animates beneath me." When set, Chromium can skip behind-blur sampling between frames.
- Practical mechanism: combine with E45 `contain: paint`.

**[E43] `requestIdleCallback` re-sample of static blur snapshots**
- For slow-changing content (e.g. Notebook list), update the snapshot only when the scheduler has spare cycles.

**[E44] `transform: translateZ(0)` to push to GPU layer**
- Sometimes paradoxically *reduces* repaint by giving the blurred surface its own layer.
- Test on Sidebar; experiment-only.

**[E45] `contain: paint` on blurred ancestors**
- Chromium hint: this subtree's paint is contained. Outside changes don't invalidate behind-blur sample.
- Cheap, often free.

**[E46] Fade in blur on tab activate**
- `transition: backdrop-filter 200ms` on tab enter (reverses E68 — animating blur is expensive in general, but a one-shot fade may be acceptable).
- Hidden cost wins: blur was never present during the transition.

**[E47] Pre-baked SVG `<filter>` applied once**
- SVG `<filter>` with `feGaussianBlur` can be applied via `filter: url(#blur)` and may have a different (sometimes lower) cost on Mac than `backdrop-filter`.

**[E48] Pre-render blurred backgrounds at design-time**
- Per theme, ship a PNG of the blurred app shell. Load as `background-image`. Zero GPU.
- Constraint: theme switching needs new asset; works for fixed-palette designs.

**[E49] `mix-blend-mode: overlay` + tint**
- Modulates color of underlying pixels without sampling them through a blur kernel.
- Cheap; reads as "tinted glass" but not "frosted."

**[E50] Manual invalidation: `data-blur-source-changed="true"` flag**
- Custom signal: blur re-samples only when a parent state declares the source changed.
- Requires runtime + maybe a custom paint worklet.

*[PIVOT]*

### Domain D6 — Perceptual budget

**[E51] Personal A/B test (you, the developer)**
- For 24 hours, set `--blur-radius-xl: 12px` globally. If you can't tell the difference, ship it.
- Highest-leverage, lowest-cost research move. Most users won't notice either.

**[E52] JND quantization {0, 4, 8, 12, 16, 24}**
- Just-Noticeable-Difference for backdrop blur is ~4px steps. Snapping to these defeats Chromium's per-radius shader miss.
- Free quality preserve.

**[E53] Saturation-only as "frosted" treatment**
- `backdrop-saturate(1.6) brightness(1.05)` reads as frosted glass to many users without any blur kernel.
- Test on T3 surfaces (sidebar, header).

**[E54] Attention-aware blur**
- Most-blurred surfaces should be where users focus least (ambient chrome). Active focus areas can have less or no blur.
- Inverted from current state: Sidebar (peripheral) has `2xl`, Modal (focal) has `xl`.

**[E55] `--glass-fidelity: 1.0` global slider**
- Single CSS variable that scales every blur radius. Default 1.0; user can dial down.
- Future-proof: ties to E10, E5, E94.

**[E56] Tier-based fidelity**
- Ambient surfaces: fidelity 0.4. Active surfaces: fidelity 1.0. Dial via CSS variable.

**[E57] Frosted-glass texture (PNG noise + light gradient overlay)**
- Designer-controlled. Looks indistinguishable from low-radius backdrop-blur to most users.
- 0 GPU cost. Bundle: ~30KB PNG.

**[E58] `backdrop-filter: saturate(1.8) brightness(1.05)`**
- Same as E53, slightly different params for variety.

**[E59] Platform-asymmetric fidelity**
- Mac: full glass (cultural expectation, native vibrancy alternatives exist).
- Linux/Windows: tinted-only (their compositors don't render this aesthetic natively anyway).

**[E60] Eliminate blur on small surfaces (<200px²)**
- Blur on a 32×32 toolbar button is imperceptible and wasteful.
- Audit: which blurred elements are <40000 px²?

*[PIVOT]*

### Domain D7 — GPU pipeline tricks

**[E61] `transform: translateZ(0)` for cache promotion**
- Promotes the blurred element to a dedicated GPU layer; Chromium may cache the blurred result across frames.

**[E62] `will-change: backdrop-filter`**
- Explicit cache hint. Use sparingly — overuse defeats it. Test on the 1–2 most stable blurred surfaces (Sidebar, Header).

**[E63] `contain: layout paint style` on blurred boxes**
- Strongest containment hint. Chromium can short-circuit invalidation propagation.
- Test on every GlassCard.

**[E64] Avoid `position: fixed` on blurred elements**
- Fixed-position layers re-composite per scroll frame. Audit: which fixed elements have blur?

**[E65] Avoid `transform` on blurred elements**
- Re-promotes layer + invalidates blur sample. Audit hover-`scale-105` and `translate-y-*` on GlassCards.

**[E66] Reduce `border-radius` complexity**
- Rounded corners require extra clipping passes. Switch from `rounded-3xl` (24px) to `rounded-2xl` (16px) on blurred elements to reduce mask cost.

**[E67] Skip blur on layers with `box-shadow`**
- Compositor double-pays for shadow + blur on same element. Either-or per surface.

**[E68] Disable `transition: backdrop-filter`**
- Animating blur radius is exorbitant. Cross-fade two opacity-keyed layers instead — same visual, cheap.

**[E69] WebGL-rendered blur as `<canvas>` background**
- Manual control: choose 30Hz update, custom kernel. Risk: implementation cost; reward: total control.

**[E70] Electron flag tuning**
- `--enable-features=BackForwardCache` — may release blur surface caches faster.
- `--disable-features=WebAuthenticationCable` — not blur-related but reduces Chromium feature surface; quick wins live in flag combos.

*[PIVOT]*

### Domain D8 — Substitution materials

**[E71] Pre-rendered noise PNG + opacity tint**
- 64×64 tiled PNG, ~3KB. CSS: `background: url(noise.png) repeat, rgba(255,255,255,0.04)`. Reads as frosted at 0 GPU.

**[E72] `mask-image: radial-gradient(...)`**
- Soft-edge tinted area without blur. Different visual but might suit Sidebar's ambient role.

**[E73] SVG turbulence filter rendered once**
- `<filter><feTurbulence/></filter>` rendered to an `<image>` background. Static, infinite reuse.

**[E74] Designer-exported blurred PNG sprites**
- Ship per-component blurred backgrounds as PNGs (drag from Figma). Pixel-perfect, 0 ongoing cost.

**[E75] Snapshot-window-bg + JS blur once**
- On launch, snapshot the window background, blur in JS, store as a base64 background. Refresh on theme change.

**[E76] CSS conic-gradient + opacity for "iridescent glass"**
- A modern alternative aesthetic — not blur but shimmer-tint. Could be a theme variant.

**[E77] IBM Carbon-style translucent panels**
- Layered semi-opaque white panels with subtle inner shadows and 1px highlights. The "professional glass" aesthetic without blur.

**[E78] `<canvas>` with `filter: blur()` rendered once**
- Different from E69: just paint the background as a static blurred canvas. No per-frame GPU, just one.

**[E79] CSS Houdini `paint()` worklet**
- Custom paint with manual blur kernel and sample rate. Cutting-edge, Chromium-only (fine for Electron).

**[E80] Static gradient + `mix-blend-mode: soft-light`**
- Modulates underlying color without blur. Cheap. Different aesthetic — "tinted" not "frosted."

*[PIVOT]*

### Domain D9 — Design-language tiers (codification)

**[E81] Document blur tiers in `design-language.md`**
- T1=full glass (modals, hero), T2=light glass (cards), T3=tinted-only (sidebar, header), T4=opaque (utility chrome).
- Codification first, enforcement second.

**[E82] Demote Sidebar.tsx:219 from T1 (`backdrop-blur-2xl`) → T3 (tinted-only)**
- Sidebar is ambient chrome. The 2xl blur is the most expensive in the app and the least focal.

**[E83] Demote SessionView.tsx scroll-edge fades from blur → gradient-only**
- 4 sites. Pure decoration. T4.

**[E84] Demote NotebookView body from T1 nested → T3**
- Keep header at T2 for sticky-glass effect; body becomes tinted.

**[E85] Promote AudioNoteModal modal blur to T1, demote BugReportModal to T2**
- AudioNoteModal is a focal experience (audio playback). BugReportModal is a transient form. Tier accordingly.

**[E86] Per-tier radius hard-coded in tokens**
- `--blur-t1: 24px; --blur-t2: 12px; --blur-t3: 4px; --blur-t4: 0px`. Components use the token, not the Tailwind class.

**[E87] `<GlassCard tier={2}>` prop**
- Components opt into a known cost. Default tier (e.g. 3) requires no decision.

**[E88] Visual regression test per tier (Playwright)**
- Snapshot each surface at known tier. Reject PRs that move a T3 surface visually closer to T1.
- Catches accidental promotion drift.

**[E89] One-pass designer audit of every blurred surface**
- You walk through the app, classify each blur as T1–T4. Most will be T3 (ambient chrome).
- Manual but high-leverage.

**[E90] Aesthetic budget per route**
- Like blur-depth budget but quality-aware: SessionView allowed 4 T1 surfaces, others max 2.
- Forces designers to prioritize.

*[PIVOT]*

### Domain D10 — Platform-conditional

**[E91] CSS detection of macOS via `data-platform="darwin"`**
- Set on `<html>` from Electron preload. CSS: `[data-platform="darwin"] .glass { backdrop-filter: blur(24px) } :not([data-platform="darwin"]) .glass { backdrop-filter: saturate(1.5) }`.

**[E92] Aggressive reduction *only* on Mac**
- The cost-benefit is asymmetric. Linux/Windows users keep full glass; Mac users get a tuned variant.
- Aligns with where the bug was reported.

**[E93] Retina-aware radius: `data-dpr="2"` halves radius**
- `window.devicePixelRatio >= 2` → smaller radius compensates for 4× pixel cost.

**[E94] ProMotion-aware radius**
- `screen.refreshRate >= 120` → halve radius. Doubled rAF rate × halved kernel = same total cost.
- Chromium 96+ exposes `screen.refreshRate`.

**[E95] Mac native vibrancy via Electron BrowserWindow**
- `vibrancy: 'sidebar'` makes macOS render the glass natively. Set `body { background: transparent }` and let the OS do it.
- **Highest single-shot impact for Mac. ZERO Chromium GPU cost for the blur.** Risk: changes window transparency; needs careful testing.

**[E96] Windows Mica via `setVibrancy` / Electron API**
- Same trick on Win11 (Mica/Acrylic). Same zero-cost result.

**[E97] Linux fallback**
- Wayland/X11 don't expose vibrancy uniformly. Use tinted-only (E19) on Linux.

**[E98] Conditional pre-rendered backgrounds**
- Ship `bg-mac.png`, `bg-win.png`, `bg-linux.png` optimized per platform compositor.

**[E99] `max-width: 100vw` clamps blurred area to current platform's viewport**
- Pedantic but real: ultrawide monitors have larger blurred surfaces.

**[E100] Detect Electron version → known-bad versions force fallback**
- M105 (Electron M4 regression hypothesis). Hardcode "if Electron version in [bad-list], use tinted variant."

*[PIVOT]*

### Domain D11 — Animation interaction

**[E101] Audit `transition: all` on blurred elements**
- Tailwind `transition-all` triggers on any animatable property change. Replace with explicit lists (`transition-[opacity,transform]`).
- Common antipattern across 36 callsites.

**[E102] Never transition `backdrop-filter` itself**
- Animating blur radius = full re-render every frame. Use cross-fade between two pre-built layers instead.

**[E103] Cross-fade two opacity-keyed blurred layers**
- Two static-radius layers; animate opacity between them. Same visual transition; constant blur cost.

**[E104] Hover transitions never change blur**
- Audit: do hover states on GlassCards animate blur properties? Strip if so.

**[E105] Audit `will-change` near blurred ancestors**
- `will-change: transform` on a sibling promotes a layer; may force the blurred neighbor to re-promote. Audit usage.

**[E106] Stop `scale-105` hover on blurred cards**
- Transforms invalidate blur sample. Replace with opacity-only hover (or a sibling-based highlight).

**[E107] `overflow: hidden` parents reduce repaint area**
- Bounds the invalidation region.

**[E108] Manually drop `will-change` post-transition**
- After transition completes, `style.willChange = 'auto'` via JS. Free's the layer for compositor.

**[E109] Tab-transition on non-blurred wrapper**
- Currently tab transitions may animate a blurred container. Move the transition to a non-blurred parent; the blurred child is static through the transition.

**[E110] Replace `transition-all` globally**
- Lint rule: ban `transition-all` on any element with `backdrop-blur`. Forces explicit property lists.

*[PIVOT]*

### Domain D12 — Content-aware blur

**[E111] Detect "is anything dynamic behind this blur?"**
- If the only thing behind a GlassCard is a static gradient, the blur is decorative — swap for tint.
- Static analysis or runtime mutation observer.

**[E112] Empty list state drops blur**
- Model tab list empty → GlassCard wrapping the list has nothing to blur. Conditionally remove blur class.

**[E113] IntersectionObserver overlap with non-static content**
- Blur only when the element overlaps a region marked `data-dynamic="true"`.

**[E114] Lazy-mount blur layer on hover/focus**
- A card without blur until interacted. Card receives focus → blur fades in.
- Quality where attention is, cost only when justified.

**[E115] Above-fold cards get blur, below-fold get tint**
- IntersectionObserver-driven tier swap.

**[E116] NotebookView: blur only when audio playing**
- Audio canvas was the dynamic content under the blur. When idle, swap to tint.

**[E117] SessionView Live mode: kill blur over inactive AudioVisualizer**
- AudioViz is gated on `isActive` (commit `048dba8`). Also strip the blur over its container during the `false` state.
- Logical extension of the AudioViz fix.

**[E118] When child modal opens, parent surface drops blur**
- Already covered as E23, restated as content-aware: "the modal IS the new content; old content's blur is invisible."

**[E119] (merge with E118)**

**[E120] Snapshot-on-stable**
- When surface beneath has been static for 2 seconds, blit a snapshot bitmap and remove `backdrop-filter`. Restore on invalidation.
- Most aggressive snapshot-blur variant.

*[PIVOT]*

### Domain D13 — Provocative / Reversal / Black-swan

**[E121] PO: "blur is free"**
- If blur cost nothing, what would change about the design? (Probably: nothing — we already act like it's free.) Surfaces our latent assumption.

**[E122] PO: "there is no blur"**
- What signals "this surface is glass" without blur? Borders, gradients, inner shadows, subtle noise, inset highlights. All free.
- Generates the substitution material list (D8) from a different angle.

**[E123] Reverse: blur the *content*, not the *backdrop***
- `filter: blur()` on a content layer with reduced opacity, over a tinted background. May be cheaper if content area < backdrop area.
- Inverted physics: usually we blur what's beneath; here we blur what's drawn.

**[E124] Worst-possible-idea: animate blur radius randomly per frame**
- What's the worst we could do? — Amusingly, transitions on `backdrop-filter` are uncomfortably close. Surfaces E102 as a real existing problem.

**[E125] User-facing "Reduced Effects" toggle in Settings**
- Explicit user control. Ships immediately, no design-language fight, gives Mac users a power-saving knob.
- "Power Saver" mode: aggressive blur reduction + AudioViz off + 1Hz polling deferred.

**[E126] Default `--glass-fidelity: 0.5`; users can crank to 1.0**
- Most users won't change it; Mac users see a 50% reduction by default.
- Pre-empts the design conversation: "we're not removing blur, we're shipping at 50% fidelity by default."

**[E127] Designer-exported blurred PNG per theme**
- Eliminates `backdrop-filter` entirely from the runtime. Designer controls quality at build-time.

**[E128] Deprecate `backdrop-filter` from the design system**
- Banned at the contract level; only allowed via opt-in `<UnsafeGlass>` escape hatch. Forces every blur to be explicitly justified.

**[E129] Black-swan: future Chromium changes blur cost model**
- We don't control Chromium. Having a kill switch (E125, E126, E55) is the only safe posture against future regressions.

**[E130] Reverse: do nothing**
- Sometimes the right answer is "the design language is more important than 20% GPU." Document the decision; close the C2-b row of the matrix as "won't fix."
- Adversarial completeness — not the recommended outcome but worth naming.

---

**Phase 1 tally:** 130 ideas across 13 orthogonal domains. Generated quantity goal exceeded; many ideas overlap (e.g. E18/E81/E86 all about tiering, E48/E74/E127 all about pre-baked PNGs). Convergence happens in Phase 2.

**Strongest leads (intuitive pre-Phase-2 ranking):**
- **E95 (native macOS vibrancy)** — eliminates Chromium blur entirely on Mac. Single highest-impact idea.
- **E51 (personal A/B at 12px)** — research-style, almost-zero-cost, may unlock E11/E55.
- **E36/E83 (drop blur on scroll-edge gradients)** — pure waste, free fix.
- **E22 (NotebookView nested blur flatten)** — direct fix to documented A3 antipattern.
- **E125/E126 (user-facing fidelity slider)** — pre-empts the design conversation.
- **E45/E63 (`contain: paint`/`contain: layout paint style`)** — Chromium hints, often free wins.
- **E81 (codify tiers in design-language.md)** — foundation for everything else.

---

## Phase 2 — Pattern Recognition (Affinity Mapping + 2×2 Matrix)

### Affinity clusters (mechanisms, not symptoms)

| Cluster | Mechanism | Member ideas | Notes |
|---|---|---|---|
| **A — Conditional gating** | Blur runs only when justified (focus/visibility/scroll/battery) | E1, E2, E3, E4, E5, E6, E7, E8, E9, E10, E114, E116, E117 | Often free; trigger logic costs ~nothing |
| **B — Radius scaling** | Token-driven radius, JND quantization, viewport/retina/ProMotion adaptation | E11, E13, E14, E15, E16, E17, E20, E51, E52, E93, E94 | Foundation cluster — most other clusters need a token |
| **C — Layer flattening** | Eliminate nested/redundant blur stacks | E12, E21, E22, E23, E24, E25, E26, E27, E28, E29, E30 | Zero visible change; pure waste removal |
| **D — Spatial confinement** | Only blur the visible/small/needed region | E31, E32, E33, E34, E35, E36, E37, E38, E40 | Mixed aesthetic cost; varies per surface |
| **E — Static substitution** | Pre-bake / snapshot / one-time render | E39, E41, E42, E43, E47, E48, E50, E73, E74, E75, E78, E120, E127 | Implementation philosophy — once accepted, dominates |
| **F — Aesthetic substitution** | Saturate, tint, noise, gradient, blend-mode (no kernel sampling) | E19, E49, E53, E57, E58, E71, E72, E76, E77, E80, E122 | Visible aesthetic shift; T3-tier candidates |
| **G — Compositor hints** | `contain`, `will-change`, `isolation`, `transform: translateZ(0)` | E45, E61, E62, E63, E64, E65, E66, E67 | Free perf when applied correctly; risk of negative if misapplied |
| **H — Animation pruning** | Kill transitions on `backdrop-filter`, audit `transition-all` | E68, E101, E102, E103, E104, E105, E106, E107, E108, E109, E110 | Free; many surfaces don't need any blur transition |
| **I — Design-language tiers** | Codify T1/T2/T3/T4 + tokens + per-tier budgets | E18, E81, E82, E83, E84, E85, E86, E87, E88, E89, E90 | Foundation — many other clusters compose with this |
| **J — Platform / native vibrancy** | OS-level glass (mac vibrancy / win Mica), Linux fallback | E59, E91, E92, E95, E96, E97, E98 | Highest impact ceiling; risk = window transparency edge cases |
| **K — User-facing fidelity** | Settings toggle + default `--glass-fidelity: 0.5` | E55, E125, E126 | UX-pre-empts-design lever |
| **L — Provocations / philosophical** | "Blur is free", "no blur", "deprecate", "do nothing" | E121, E122, E123, E124, E128, E129, E130 | Frame the meta-decisions; not directly implementable |

### Cluster-level meta-observations

1. **Cluster I (tiers) is foundational.** Almost every other cluster cleanly composes with a tier system. Without tiers, every change is per-component bikeshed. With tiers, changes are per-tier policy. **Recommend: ship I first.**

2. **Clusters A + C + G + H are "no-aesthetic-cost" clusters.** Together they cover 40+ ideas, none of which require a design-language conversation. They should ship as one coherent perf wave.

3. **Cluster E (static substitution) is an implementation philosophy.** If accepted, it dominates the runtime — most of A/G/H become moot. If rejected, it's just one of many tools. **Decide on E first** before sequencing the others.

4. **Cluster J is asymmetrically valuable.** Native vibrancy is a single change with the largest single-shot impact (E95). The remaining J ideas are window-dressing.

5. **Cluster L doesn't ship code, but it shapes Phase 3/4 decisions.** Treat as steering, not deliverable.

---

### 2×2 Matrix — GPU reduction impact × Aesthetic cost

```
                       AESTHETIC COST
                  Low (preserves glass)        High (visible shift)
                ┌──────────────────────────┬──────────────────────────┐
        High    │                          │                          │
        Impact  │   Q1: SHIP NOW           │   Q2: DESIGN CONVO       │
                │   E22, E36, E83          │   E31, E48/E74/E127,     │
                │   E25, E45, E63          │   E59, E92, E126,        │
                │   E68, E101, E102, E110  │   E128, E32, E39         │
                │   E95, E96               │                          │
                │   E51 (research)         │                          │
                ├──────────────────────────┼──────────────────────────┤
        Low     │                          │                          │
        Impact  │   Q3: NICE TO HAVE       │   Q4: AVOID              │
                │   E13, E16, E66          │   E69, E79, E76          │
                │   E61, E62, E107, E108   │   E130                   │
                │   E105                   │                          │
                │                          │                          │
                └──────────────────────────┴──────────────────────────┘
```

### Q1 — Ship Now (sweet-spot quadrant)

High GPU impact AND low/no aesthetic cost. These should be sequenced into the implementation roadmap.

| ID | Action | Why Q1 |
|---|---|---|
| **E22** | Flatten NotebookView nested blur (lines 725, 727) — keep one tier | Eliminates a documented antipattern (`design-language.md:61`); visual difference imperceptible |
| **E25** | Audit App.tsx 8 blur uses; flatten the nested ones | Same mechanism as E22 at scale; the highest-density file |
| **E36 / E83** | Drop `backdrop-blur-sm` on the 4 SessionView scroll-edge fades | Pure decoration; gradient produces the visual; the blur was waste |
| **E45 / E63** | `contain: paint` / `contain: layout paint style` on every GlassCard root | Compositor hint; zero visual change; often free perf |
| **E68** | Disable any `transition: backdrop-filter` | Animating blur radius is exorbitant; cross-fade two layers (E103) for the rare case it's needed |
| **E101 / E102 / E110** | Replace `transition-all` with explicit lists on every blurred element | Common Tailwind antipattern; lint-rule enforceable |
| **E51** | Personal A/B at `--blur-radius-xl: 12px` for 24h | Research; if no perceptible difference, unlocks E11+E55 globally |
| **E95** | Native macOS vibrancy via Electron BrowserWindow + transparent body | Single largest impact; visually equivalent on Mac; risk = window transparency edge cases need careful test |
| **E96** | Windows Mica via `setVibrancy` | Same trick on Win11; same risk profile |
| **E30** | New ui-contract rule: no nested `backdrop-blur` | Regression guard; codifies the antipattern fix |

**Q1 predicted aggregate impact:** 30–60% Mac idle GPU reduction (E95 alone is 50%+), 10–20% on Linux/Windows.

### Q2 — Design Conversation Required

High impact but visible aesthetic shift. These need an explicit aesthetic decision before shipping.

| ID | Action | Decision needed |
|---|---|---|
| **E31** | Confine blur to chrome only (no blur on content surfaces) | Are content surfaces glass or solid? |
| **E48 / E74 / E127** | Pre-rendered blurred PNGs (per theme) instead of `backdrop-filter` | Accept design-time blur, lose runtime adaptation? |
| **E126** | Default `--glass-fidelity: 0.5` | Ship with reduced default fidelity, user can crank up? |
| **E128** | Deprecate `backdrop-filter` from design system; opt-in only | Most aggressive; reframes the entire design language |
| **E59 / E92** | Mac-only full glass; Linux/Windows tinted-only | Accept platform asymmetry? |
| **E32** | Frosted-edge only (1px ring of blur, opaque interior) | Major visual change; "glass" perception shifts |
| **E39 / E84** | NotebookView body: noise-texture instead of blur | Different aesthetic in one specific view |
| **E125** | User-facing "Reduced Effects" toggle in Settings | Cheap to ship but adds a settings surface |

**Strategy for Q2:** treat as a separate decision wave after Q1 ships. Run a "designer pass" (E89) over Q2 candidates before deciding.

### Q3 — Nice to Have (low priority)

Low impact, low cost. Bundle opportunistically.

| ID | Action | Why low priority |
|---|---|---|
| E13 | Quantize radius to 4px steps | Marginal shader cache win; tiny |
| E16 | Viewport-clamped radius | Helps narrow-window users only |
| E66 | Reduce `border-radius` complexity | Marginal clipping cost |
| E61 / E62 | `translateZ(0)` / `will-change` cache promotion | Risk of negative impact if misapplied |
| E107 / E108 | `overflow: hidden` parents / drop `will-change` post-transition | Polish |
| E105 | Audit `will-change` near blurred ancestors | Cleanup |

### Q4 — Avoid

Low impact, high cost. Don't pursue unless other paths fail.

| ID | Why avoid |
|---|---|
| E69 | WebGL-rendered blur from scratch — high implementation cost for marginal win |
| E79 | Houdini `paint()` worklet — bleeding-edge for a niche application |
| E76 | Conic-gradient iridescent — different aesthetic, similar cost |
| E130 | "Do nothing" — surfaced for completeness, not recommended |

### Strategic decisions surfaced by Phase 2

Before Phase 3, three meta-decisions shape the rest:

**Decision 1: Native vibrancy (E95/E96) — yes / no / experimental?**
- If **yes**: it's the highest-leverage move; everything else is supplementary on Mac.
- Risk: requires `BrowserWindow({ vibrancy, transparent })` configuration; may break theme switching, screenshot capture, window dragging.
- Recommended posture: **prototype on a feature branch, ship behind a settings flag initially.**

**Decision 2: Design-language tiers (Cluster I) — codify before or after Q1 ships?**
- If **before**: Q1 ships into a structured framework; per-tier policies are durable.
- If **after**: Q1 ships ad-hoc; tiers are reverse-engineered from what we did.
- Recommended posture: **codify minimal tiers (T1-T4 with one example per tier) before Q1, leave full audit (E89) for after.**

**Decision 3: Static substitution (Cluster E) — accept the philosophy or not?**
- If **yes**: pre-baked PNGs / snapshots become the default treatment for non-modal glass; runtime `backdrop-filter` becomes the exception.
- If **no**: runtime stays the norm; we optimize what's there.
- Recommended posture: **defer this decision** — Q1 doesn't require it, and Q2's pre-rendered options can be evaluated standalone.

### What Phase 2 demoted or rejected

- **Cluster D (spatial confinement)** is split: E36/E83 land in Q1 (free), E31/E32 land in Q2 (visible), most others (E33, E37, E38, E40) are surface-specific judgment calls best handled in the designer audit (E89).
- **Cluster F (aesthetic substitution)** is mostly Q2 — these are real design changes, not stealth perf wins. Treat as fall-back if Q1+J don't land the targets.
- **Cluster L (provocations)** is steering only — none ship as code.

---

**Phase 2 status:** complete. Q1 has 10 actions ready for Phase 3 decomposition. Q2 has 8 actions awaiting designer review. Three meta-decisions documented for Phase 3/4 to honor.

---

## Phase 3 — Idea Development (Decomposition + What-If Stress Test)

Top Q1 actions decomposed into PR-shaped units. Each block: file anchor → code change → what-if stress tests → residual risk.

### F1. Codify minimal blur tiers in `design-language.md` (E81)

**Why first:** every other action references "tier" implicitly. Without codification, each PR re-bikesheds the question.

**Files:** `dashboard/design-language.md` (or wherever the project's design doc lives), `dashboard/src/styles/tokens.css` (or equivalent).

**Code change:**
- Append section: "Glass surface tiers"
  - **T1** — focal modal glass. Radius 24px, max 1 surface visible at a time. `backdrop-blur-xl`. (e.g. SettingsModal panel, AudioNoteModal panel.)
  - **T2** — card glass. Radius 12px, multiple visible OK. `backdrop-blur-md`. (e.g. GlassCard rows on Session/Notebook.)
  - **T3** — ambient chrome. Tinted only — no `backdrop-filter`; `bg-white/8 backdrop-saturate-150`. (e.g. Sidebar, Header.)
  - **T4** — utility / decorative. No glass treatment. Solid or gradient only. (e.g. scroll-edge fades.)
- Add CSS tokens: `--blur-t1: 24px; --blur-t2: 12px; --blur-t3: 0px; --blur-t4: 0px`.
- Update `ui-contract` schema to track `tier` per surface (optional v2).

**What-if 1 — "ship lands but reporter says GPU still high":**
- This action ships *no GPU change* — it's documentation. Failure mode: subsequent PRs ignore the tiers. Mitigation: ui-contract enforcement (V2).

**What-if 2 — "designer pushes back on T3 = no blur":**
- Sidebar in particular may be defended as identity. Fallback: T3 = `blur(4px) + saturate(1.5)` instead of saturate-only. Costs less than current `2xl` (40px) by ~10×.

**Residual risk:** Low. Documentation-only PR.

**Verification:** Reviewed by designer (you); accepted into design-language.md.

---

### F2. Native macOS vibrancy (E95) + Windows Mica (E96)

**Why high-priority:** single largest GPU reduction on the worst-affected platform. Eliminates Chromium `backdrop-filter` cost entirely for the window background.

**Files:**
- `electron/main.ts` (BrowserWindow construction)
- `electron/preload.ts` (set `data-platform` and vibrancy state on document)
- `dashboard/src/index.css` (CSS rules for `[data-vibrancy="active"]`)

**Code change:**
- macOS: `BrowserWindow({ vibrancy: 'sidebar', visualEffectState: 'active', backgroundColor: '#00000000', transparent: true, ... })`. Documented in Electron docs; production-tested.
- Windows: `win.setVibrancy('mica')` (Win11) or `win.setVibrancy('acrylic')` (Win10 fallback). API is `electron@>=29`.
- Linux: no vibrancy API — fall through to T3 tinted-only treatment.
- CSS: when `[data-vibrancy="active"]`, body background becomes transparent and the OS-rendered vibrancy shows through. App-level glass surfaces (modals, cards) keep their blur — but the *window background* (the largest blurred area) is now free.

**What-if 1 — "vibrancy active but Mac reporter says CPU/GPU still high":**
- Means our app-level GlassCards and modals still cost. F1+F3+F5 attack those. E95 only handles the window background.
- Diagnostic: per-process Activity Monitor delta before/after vibrancy enable.

**What-if 2 — "vibrancy breaks something visible":**
- Possible regressions: theme switching (transparent body affects dark-mode background), screenshot capture, full-screen mode, drag-to-resize regions.
- Mitigation: ship behind a settings flag (`useNativeGlass: true` default on macOS, opt-in on Windows). Roll back is a one-line config change.

**What-if 3 — "different macOS / Windows version doesn't support":**
- macOS Sequoia 15.x is current target; vibrancy supported since 10.14. Should be safe.
- Windows Mica requires Win11 build 22000+. Acrylic fallback for older.

**Residual risk:** Medium. Window-transparency edge cases require Mac/Win tester runs. Settings-flag mitigation makes it reversible.

**Verification:**
- Mac reporter (issue #87): per-process CPU/GPU before/after vibrancy enable.
- Visual regression: dark mode background, fullscreen mode, screenshot capture.

---

### F3. Flatten nested blurs (E22, E25)

**Why high-priority:** zero visible change; eliminates the documented A3 antipattern (`design-language.md:61` already warns about it).

**Files:**
- `dashboard/components/views/NotebookView.tsx:725, 727` — has both `backdrop-blur-xl` (container) AND `backdrop-blur-md` (header).
- `dashboard/App.tsx` — 8 blur uses; audit which are nested.
- `dashboard/components/views/AudioNoteModal.tsx` — 5 blur uses; audit.

**Code change:**
- NotebookView: keep `backdrop-blur-md` on the sticky header (T2 tier), drop the parent's `backdrop-blur-xl` (becomes T3 tinted via `backdrop-saturate-150`).
- App.tsx: visual map of the 8 blur sites, classify each as {parent, nested-child}. For each nested-child, drop the inner blur if outer is sufficient; for each independent, leave as-is.
- AudioNoteModal: same audit on 5 sites.

**What-if 1 — "ship but Mac reporter says GPU still high":**
- Means F2 (vibrancy) is doing the bulk of work; F3 is supplementary. Still ship — it removes documented waste.

**What-if 2 — "visual review catches a regression":**
- Likely surface: a modal that depended on the parent's blur to dim the background. Mitigation: replace the dropped blur with a `bg-black/40` scrim if needed.
- Quick rollback: revert per-component, since each is independent.

**Residual risk:** Low. Each component is independent; per-PR rollback is trivial.

**Verification:**
- Visual diff (Playwright screenshot per affected component).
- ui-contract per-file budgets drop (NotebookView 4→3, AudioNoteModal 5→3, App.tsx 8→4 expected).

---

### F4. Drop blur on SessionView scroll-edge fades (E36 / E83)

**Why high-priority:** pure decoration. The gradient produces the visual; the `backdrop-blur-sm` was unjustified.

**Files:**
- `dashboard/components/views/SessionView.tsx:1174, 1774, 1799, 2279` — four sites with `bg-linear-to-* from-white/10 to-transparent backdrop-blur-sm`.

**Code change:**
- Strip `backdrop-blur-sm` from each. Keep the gradient.
- Optionally bump opacity slightly (`from-white/15`) to compensate visually.

**What-if 1 — "ship but reporter says scroll artifacts (S4) still present":**
- Already attacked by commit `66473b4` (content-visibility on rows). This is incremental; if S4 persists, look at GlassCard's own `backdrop-blur-xl` (F3 may not have touched it).

**What-if 2 — "fades look weaker without blur":**
- Bump gradient opacity by 50% and add a subtle inner `box-shadow: inset 0 -8px 12px rgba(0,0,0,0.1)` for depth.
- If still visually unacceptable: this drops out of Q1 into Q2 (designer review).

**Residual risk:** Very low. Four-line change, isolated to one file.

**Verification:**
- Visual diff at top/bottom scroll positions.
- ui-contract: SessionView budget drops from 4.

---

### F5. `contain: paint` and `contain: layout paint style` on GlassCard (E45 / E63)

**Why high-priority:** zero visual change; compositor hint that often delivers free perf.

**Files:**
- `dashboard/components/GlassCard.tsx` — base GlassCard component.
- Optionally: ModelManagerTab row wrappers (already has `content-visibility: auto` from commit `66473b4`).

**Code change:**
- Add `contain: 'paint'` (or `'layout paint style'` for stronger isolation) to GlassCard's root style.
- Test on Linux/Windows first to confirm no negative impact (containment can occasionally clip absolute-positioned children).

**What-if 1 — "containment clips a Select dropdown":**
- Same risk encountered in commit `66473b4` (selectOpen toggles `content-visibility`). Use the same trick: when a child popover opens, downgrade containment via `data-popover-open` attribute.
- Pattern is already proven in ModelManager.

**What-if 2 — "no measurable perf delta":**
- Compositor hints are best-case. Worst case = neutral. Still ship as a defensive pattern.

**Residual risk:** Low-medium. Containment edge cases require manual visual test of every dropdown/popover/tooltip on a GlassCard.

**Verification:**
- Manual: open every dropdown / tooltip / popover that lives inside a GlassCard, confirm not clipped.
- Playwright snapshot of Settings + Notebook tabs.

---

### F6. Kill `transition: backdrop-filter` + audit `transition-all` (E68, E101, E102, E110)

**Why high-priority:** animating blur is exorbitant; `transition-all` is a Tailwind antipattern that captures `backdrop-filter` accidentally.

**Files:** broad — every blurred component using `transition-*`.

**Code change:**
- Grep for `transition-all` in `dashboard/components/**/*.tsx` and `dashboard/src/**/*.tsx`. Replace each with explicit lists (e.g. `transition-[opacity,transform]`).
- Specifically search for `transition.*backdrop` — should yield zero matches after the change.
- Add ESLint rule (or ui-contract rule): `transition-all` is banned on any element with `backdrop-blur-*`.

**What-if 1 — "transitions look choppy":**
- Means the animated property wasn't in the explicit list. Audit and add. (e.g. `transition-[opacity,transform,colors]`.)

**What-if 2 — "the lint rule is too strict":**
- Allow `transition-all` if no `backdrop-blur-*` on the same element. Rule scope is per-element, not file-wide.

**Residual risk:** Low. Mechanical replacement.

**Verification:**
- Grep: `rg "transition-all" dashboard/components/ dashboard/src/` should return only non-glass elements.
- Manual: hover/click/scroll through every glassy surface, confirm transitions feel right.

---

### F7. Personal radius A/B at 12px (E51)

**Why include:** research-style, near-zero cost, may unlock global radius reduction (a meaningful additional cluster).

**Files:**
- `dashboard/src/index.css` (or tokens file)

**Code change:**
- Add `--blur-radius-default: 12px` token.
- Either: (a) override Tailwind to use the token, or (b) hand-replace `backdrop-blur-xl` with `backdrop-blur-md` in 5 visible high-traffic surfaces (modals, GlassCard).
- Use for 24h.

**What-if 1 — "you can tell the difference":**
- Step radius up to 16px and retry. Find the JND threshold.
- If threshold is 24px (i.e. you can always tell), this idea fails — no global radius reduction; per-surface tier overrides only.

**What-if 2 — "you can't tell, but a designer can":**
- Settle at the threshold value. Document the rationale.

**Residual risk:** None — this is research, not a ship.

**Verification:** subjective, your eyes. Optional: an A/B screenshot pair shown blind to a friend.

---

### F8. ui-contract: no nested `backdrop-blur` rule (E30)

**Why include:** regression guard for F3. Without enforcement, F3's flattening will drift back over time.

**Files:**
- `dashboard/scripts/ui-contract/extract-facts.mjs` (or wherever the contract scanner lives — already has `blurScanFiles()` from commit `97c525d`).
- `dashboard/ui-contract/transcription-suite-ui.contract.yaml` (rule definition).

**Code change:**
- Add a structural check: per file, no `backdrop-blur-*` element may have an ancestor with `backdrop-blur-*` (in JSX tree). Implementation is roughly: walk JSX, track blur-class state on stack; flag any push when stack is non-empty.
- New issue code: `nested_blur_detected`.
- Add to test suite (3 cases: pass, single-nest, double-nest).

**What-if 1 — "false positive on a legitimate nesting":**
- Per-file allowlist: `nested_blur_overrides: { 'App.tsx': ['SettingsModal'] }` with a `reason:` string.
- Same pattern as the existing per-file budgets.

**What-if 2 — "scanner can't reliably detect nesting in a JSX tree across components":**
- Compromise: detect nesting only within the same file. Cross-component nesting (parent in App.tsx, child in `<Modal>`) is best-effort.
- Document the limitation.

**Residual risk:** Medium. JSX static analysis is tricky; conservative implementation may over- or under-flag.

**Verification:** unit tests + manual inspection of one false positive (if any).

---

### F-deferred: `--blur-radius-xl` token (E11) and `--glass-fidelity` (E55)

**Why deferred:** depends on F7 outcome. If F7 confirms 12px is acceptable, both tokens become obvious. If F7 fails, we still need a token but per-tier (F1) suffices.

**Status:** revisit after F7 ships.

---

### F-Q2 candidates (NOT decomposed yet — awaiting designer pass)

- **E125 / E126** — user-facing fidelity slider + default 0.5. Cheap to ship, but the default-0.5 decision is a design call.
- **E31 / E32** — confine blur to chrome / frosted-edge only. Visual shift, T3 candidates.
- **E48 / E74 / E127** — pre-rendered blurred PNGs. Implementation philosophy decision (Cluster E).
- **E59 / E92** — platform-asymmetric glass. Decide after F2 lands.

---

### Phase 3 cross-cutting risks

1. **Verification is Mac-bound for F2 and indirect for F3/F4/F5/F6.** Without a Mac collaborator, we ship and ask the reporter. Same constraint as the original RCA — no new blocker.
2. **F2 (vibrancy) is the only one where rollback is a config flip; everything else is per-component code revert.** F2 should ship behind a settings flag (`useNativeGlass`) for the first release.
3. **F1 (tiers) is documentation; if other PRs land before F1 they should still work, but tier-tagging will be retrospective.** Recommend F1 land first or at least concurrent with F2.

---

**Phase 3 status:** complete. 8 PR-shaped actions decomposed (F1–F8) plus F-deferred and F-Q2 categories. Each has anchor files, code-change description, two what-if stress tests, and a verification path.

---

## Phase 4 — Action Planning (Phased Roadmap with Verification Gates)

The original RCA's Solution Matrix row **C2-b** ("Audit + dedup backdrop-blur layers, 20–40% impact, M effort, Med ship risk") is now refined into four sequenced waves with explicit verification gates between them.

### Wave 1 — Foundation + Zero-Risk Wins  *(target: 1 PR or split into 2–3 small ones)*

**Goal:** ship documented antipatterns + free wins without any aesthetic decision. Establish tier vocabulary so later waves have a target language.

| ID | Action | Effort | Ship risk | Predicted impact (idle GPU) |
|---|---|---|---|---|
| **F1** | Codify T1–T4 tiers in `design-language.md` + add tokens | S | None | 0% (foundation) |
| **F3** | Flatten nested blurs (NotebookView, App.tsx, AudioNoteModal audit) | M | Low | 5–10% |
| **F4** | Drop `backdrop-blur-sm` on SessionView scroll-edge fades | S | Very Low | 1–3% |
| **F6** | Kill `transition: backdrop-filter` + audit `transition-all` on blurred elements | M | Low | 2–5% (idle); larger during interaction |
| **F8** | ui-contract `nested_blur_detected` rule | M | Low | 0% (regression guard) |

**Wave 1 aggregate:** 8–18% idle GPU reduction. Zero design-language conversation required.

**Verification gate before Wave 2:**
- ✅ ui-contract `npm run ui:contract:check` passes with new rules.
- ✅ Visual regression suite passes (Playwright snapshots).
- ✅ Per-file blur budgets drop where flattening occurred (e.g. NotebookView 4→3).
- ✅ Optional: Mac reporter confirms any movement on idle CPU/GPU numbers.

**Branch / PR strategy:** one branch per F-action; reviewable independently. F1 should merge first so other PRs can reference the tiers.

---

### Wave 2 — Compositor Hints + Research  *(target: 1 PR + 1 research note)*

**Goal:** apply free compositor hints; complete the radius-perception research that gates the global token work.

| ID | Action | Effort | Ship risk | Predicted impact (idle GPU) |
|---|---|---|---|---|
| **F5** | `contain: paint` / `contain: layout paint style` on GlassCard | S | Low-Med (popover clipping risk) | 5–15% |
| **F7** | Personal A/B at 12px radius for 24h | S (your time only) | None (research) | gates F-deferred |

**Wave 2 aggregate:** 5–15% additional idle GPU reduction. Research result determines whether F-deferred ships in Wave 3.

**Verification gate before Wave 3:**
- ✅ All popovers/dropdowns/tooltips inside GlassCards open without clipping.
- ✅ Optional: Playwright checks for at least 5 known popover surfaces.
- ✅ F7 research note appended to this brainstorming file with the verdict (12px acceptable / not / threshold = N).

---

### Wave 3 — Native Vibrancy *(target: 1 PR, ship behind flag)*

**Goal:** the highest-leverage move on the platform that reported the bug.

| ID | Action | Effort | Ship risk | Predicted impact (idle GPU on Mac) |
|---|---|---|---|---|
| **F2** | Mac `BrowserWindow({ vibrancy: 'sidebar', transparent: true })` + Windows `setVibrancy('mica')` + Linux fallback | L | Med-High (window-transparency edges) | **30–60% on Mac** |
| **F-deferred** (if F7 passed) | Global `--blur-radius-default` token tuned to F7 result | S | Low | 5–15% across all platforms |

**Wave 3 aggregate (Mac):** 35–75% additional idle GPU reduction *over Wave 1+2*.
**Wave 3 aggregate (Linux/Windows):** 5–15% from F-deferred only.

**Ship strategy for F2:**
- New setting: `Settings → Appearance → Use native window glass (macOS / Windows)`. Default **on** for macOS, **off** for Windows initially.
- Settings persisted in user config. Renders the OS effect via `setVibrancy()` at runtime — no relaunch required (Electron 29+).
- Telemetry-free: rely on issue #87 reporter for confirmation.

**Verification gate before Wave 4:**
- ✅ Mac reporter (issue #87) confirms before/after delta with the flag enabled.
- ✅ macOS visual checks: light/dark theme transparency, fullscreen mode, Stage Manager, screenshot capture, drag-resize regions.
- ✅ Windows 11 visual check on a Win11 machine (you or a tester).
- ✅ Linux visual check: confirms fallback path renders T3 tinted treatment correctly.
- ✅ Issue #87 close criteria met: idle CPU < 2%, idle GPU helper < 1%, no tab flicker on Model entry, no scroll repaint artifacts.

---

### Wave 4 — Designer Conversation (Q2)  *(target: deferred until Mac confirms)*

**Goal:** the aesthetic-impact tradeoffs. Trigger only if Wave 3 doesn't fully resolve issue #87, or if you want additional headroom.

| ID | Action | Effort | Aesthetic decision required |
|---|---|---|---|
| **E89** | Designer audit — walk every blurred surface, classify T1/T2/T3/T4 | M | yes (you, in design hat) |
| **E125 + E126** | User-facing "Reduced Effects" toggle + default `--glass-fidelity: 0.5` | M | yes (default fidelity choice) |
| **E48 / E74 / E127** | Pre-rendered blurred PNGs per theme | L | yes (philosophy: build-time vs runtime glass) |
| **E31 / E32** | Confine blur to chrome / frosted-edge only | M | yes (major visual shift) |
| **E59 / E92** | Platform-asymmetric glass quality | S | yes (accept platform parity loss) |

**Wave 4 trigger conditions (any one):**
- Wave 3's vibrancy fix doesn't fully meet issue #87's close criteria.
- A new GPU-related issue is filed.
- Project decides to formalize the design language and runs E89 proactively.

---

### Cumulative impact projection

| After | Mac idle GPU reduction | Linux/Windows idle GPU reduction | Issue #87 status |
|---|---|---|---|
| Pre-existing (commits 048dba8, 66473b4) | 40–60% | 20–40% | partially fixed; reporter not confirmed |
| **+ Wave 1** | 48–68% | 28–48% | likely sufficient; pending confirmation |
| **+ Wave 2** | 53–78% | 33–58% | likely sufficient |
| **+ Wave 3 (F2 vibrancy + F-deferred)** | 75–95% | 38–65% | almost-certainly sufficient; ready to close |
| **+ Wave 4** | 85–98% | 50–80% | overkill; only if needed |

Ranges are lower-bounded by the prior session's 70–90% prediction (3-change fix from RCA) and upper-bounded by the residual-cost predictions in Drill 2.3.

### Mapping to original Solution Matrix

| Original C2-b row | Refined deliverable |
|---|---|
| Likelihood: High | Confirmed by F3 audit (real nested blurs found) |
| Static-confirmable: ⚠️ partial | F3+F4 confirmed via grep + visual; F2 requires Mac tester |
| Fix effort: M | Refined to: M for Wave 1, S for Wave 2, L for Wave 3 |
| Impact: 20–40% | Refined to: 8–18% (W1) + 5–15% (W2) + 30–60% Mac (W3) — **conservatively 43–93% on Mac when stacked** |
| Ship risk: Med | Refined to: None (W1), Low-Med (W2), Med-High (W3) — settings-flag mitigation lowers W3 |
| Reg-guard: ✅ ui-contract blur-depth | Refined to: existing budget rule + F8 nested-blur rule |

### Open questions / decisions for the user

1. **Should F1 (tiers) merge before any other PR, or concurrent?** Recommendation: **before** — gives other PRs a target tier to reference.
2. **Is F2 (native vibrancy) acceptable as the headline change, or too invasive for now?** Recommendation: ship behind flag, default on for macOS, off for Windows until tested.
3. **Should F7 (personal A/B) happen before W3 ships, in parallel, or after?** Recommendation: in parallel with W1 — your eyes are the only required resource, and the result unlocks F-deferred for W3.
4. **Wave 4 — do we want to plan the designer audit (E89) now, or leave it on the shelf?** Recommendation: leave on the shelf; revisit after Mac reporter confirms W3.

---

## Extension Session Summary

**Methodology:** Progressive Technique Flow extension — Morphological+SCAMPER (130 ideas, 13 domains, anti-bias domain pivot every 10), Affinity Mapping + 2×2 (12 mechanism clusters → 4 quadrants on impact × aesthetic-cost), Implementation Decomposition + What-If (8 PR-shaped actions F1–F8 each with two stress tests), Phased Roadmap (4 waves with explicit verification gates).

**Conclusion:** the unfinished C2-b row of the original RCA Solution Matrix expands into a 4-wave plan. Wave 1 ships zero-risk wins + tier vocabulary (8–18% idle GPU win, no design conversation). Wave 2 ships compositor hints and the radius-research result (5–15% more). Wave 3 ships the headliner: native macOS vibrancy + Windows Mica behind a settings flag (30–60% additional Mac idle GPU win). Wave 4 is reserved for design-conversation work if Wave 3 doesn't close the issue.

**The two highest-leverage moves are:**
1. **F2 (native macOS vibrancy)** — single-shot, eliminates Chromium `backdrop-filter` cost for the window background entirely. Highest impact, medium ship risk, mitigated by settings flag.
2. **F1 (codify tiers)** — foundation for everything else. No GPU impact directly, but every later change becomes durable instead of bikeshedded.

**Predicted aggregate impact:** 75–95% idle GPU reduction on Mac after Wave 3, satisfying issue #87's likely close criteria.

**Verification path:** Mac reporter on issue #87 confirms before/after delta with vibrancy flag enabled, plus visual regression suite for the supporting waves.

**Regression guard:** existing `blur_depth_budget` rule + new `nested_blur_detected` rule (F8) + tier vocabulary in `design-language.md` (F1) makes the antipatterns documented, enforced, and monitored.

**Ideas generated this extension:** 130. **Total ideas across both sessions:** 235.
**Techniques used (extension):** Morphological+SCAMPER, Affinity Mapping + 2×2, Implementation Decomposition + What-If, Phased Roadmap with Verification Gates.

### Decisions for next session (implementation)

Use Wave 1's F1+F3+F4+F6+F8 as the immediate implementation set. Sequence F1 first; the others are independent. Treat F2 (vibrancy) as a separate PR with extra reviewer time and the settings-flag scaffold. F7 (personal A/B) is a research task — schedule it concurrently with Wave 1.

---

## Decisions Recorded (2026-04-25, user response to Phase 4 open questions)

| Q | Decision | Implication |
|---|---|---|
| **Q1: F1 (tiers doc) before W1 PRs or concurrent?** | **Concurrent** | F1 ships in parallel with F3/F4/F6/F8. Other PRs may reference tier names that aren't yet documented; `design-language.md` lands in the same merge window. No hard ordering dependency. |
| **Q2: F2 (native vibrancy) acceptable as headline change behind flag?** | **Yes** | F2 will ship in W3 as the headline. Settings flag `useNativeGlass` defaults on for macOS, off for Windows until tested. Visible in Settings → Appearance. |
| **Q3: F7 (personal 12px A/B) scheduled now in parallel with W1?** | **Yes** | User runs the 24-hour A/B during W1's implementation window. Result determines whether F-deferred (`--blur-radius-default` token) ships in W3 or is dropped. |
| **Q4: W4 designer audit / Q2 candidates — plan now or shelf?** | **Shelf** — added to `_bmad-output/implementation-artifacts/deferred-work.md` as a single bundled pointer entry. | Wave 4 work (E89, E125/E126, E48/E74/E127, E31/E32, E59/E92) is captured but not scheduled. Trigger conditions remain as documented in Phase 4. |

### Updated implementation order (post-decisions)

**Sprint 1 (immediate, parallel work):**
- **PR-A:** F1 — codify T1–T4 tiers in `design-language.md` + add CSS tokens
- **PR-B:** F3 — flatten nested blurs (NotebookView 725/727 + App.tsx 8-blur audit + AudioNoteModal 5-blur audit)
- **PR-C:** F4 — drop `backdrop-blur-sm` on SessionView scroll-edge fades (lines 1174, 1774, 1799, 2279)
- **PR-D:** F6 — kill `transition: backdrop-filter` + audit `transition-all` on all blurred elements (+ optional ESLint/contract rule)
- **PR-E:** F8 — ui-contract `nested_blur_detected` rule + tests
- **User task (parallel):** F7 — set `--blur-radius-default: 12px` (or hand-replace 5 high-traffic surfaces with `backdrop-blur-md`), use for 24h, record verdict back to this file

**Sprint 2:**
- **PR-F:** F5 — `contain: paint` / `contain: layout paint style` on GlassCard root (+ popover-clip safety pattern from commit `66473b4`)
- **F-deferred:** if F7 result is positive, ship `--blur-radius-default` token globally as part of PR-F or follow-on PR

**Sprint 3 (headline):**
- **PR-G:** F2 — native macOS vibrancy + Windows Mica behind `useNativeGlass` settings flag (Settings → Appearance). Mac default on, Windows default off.
- **Verification:** ask issue #87 reporter to enable flag, report before/after CPU/GPU.

**Sprint 4 (conditional, deferred):**
- W4 work (designer audit + Q2 candidates). Deferred to `_bmad-output/implementation-artifacts/deferred-work.md`. Trigger only if W3 fails to close issue #87 or a new GPU-related issue is filed.

### Updated frontmatter

`extension_status: 'complete-decisions-recorded'`
`extension_implementation_sprints: 4` (Sprint 1–3 immediate, Sprint 4 conditional/deferred)
`f7_research_owner: 'user'` (your 24-hour personal A/B)







