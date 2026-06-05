# Deferred Work

## Triage Rule

Before appending an item to this file, it must clear **all** of:

1. **Severity is MEDIUM or higher** — user-visible symptom, not a latent/theoretical hazard.
2. **Not pre-existing** — caused by the sprint under review, or surfaced a symptom the sprint was meant to close but didn't.
3. **Not already owned by a named future milestone** (M6/M7/a11y sweep/etc.) — if it has an owner, track it there, not here.
4. **Defense shape is concrete** — not "if a real user complains" or "when telemetry lands."

If any check fails, **do not append**. Close the concern in-review or drop it.

LOW-severity items, "pre-existing" hazards, TOCTOU races requiring deliberate mutation, test-coverage gaps for un-bugged branches, and cosmetic polish do **not** belong here.

When an item ships, **delete the entry** — git history + the spec file are the durable record. This file is the active queue, not a changelog.

---

## Active Items

### gh-86 no. 2 — Pyannote diarization fails on Mac M4Pro Metal bare-metal (MEDIUM)

**Symptom (reported 2026-04-19, Issue #86 item 2):** On Mac M4Pro, Metal mode, model `mlx-community/parakeet-tdt-0.6b-v3`, importing a file and transcribing with **Sortformer (Metal)** diarization works; switching to **Pyannote (`pyannote-speaker-diarization-community-1`)** does NOT work. HF token is set with fine-grained access for the gated repo and access has been granted on the model page. Reporter says logs are also empty (the empty-log issue was split off as Goal A and shipped via `spec-gh-86-mlx-log-pipeline-gaps.md`).

**Why deferred (split per Quick Dev workflow 2026-04-26):**
1. Independently shippable from the Goal A "record button disabled" fix — different code path entirely (server-side STT + diarization wiring vs. dashboard renderer gate).
2. Severity is MEDIUM — user-visible (one of two diarizer choices flat-out fails on a supported platform), but a working alternative (Sortformer) exists, so not blocker.
3. Not pre-existing — actively reported against latest DMG (v1.3.3).
4. No named milestone owner.
5. Defense shape is concrete — investigation must answer: does pyannote's PyTorch model load on Apple Silicon bare-metal at all? What device does the diarizer pick (MPS / CPU)? Does the failure show in the server logs (now visible after Goal A shipped)?

**Investigation needed before fix:**
- Read `server/backend/core/diarization/` (or wherever pyannote is wired) — confirm device selection logic for Apple Silicon bare-metal (no CUDA, MPS or CPU fallback).
- Check whether `pyannote.audio 4.0.4` is even installed on the bare-metal Apple Silicon path — the `mlx` extra is mutually exclusive with `whisper`/`nemo`/`vibevoice_asr` extras (see `[tool.uv] conflicts`); is pyannote bundled in the MLX extra or separately?
- Cross-reference the `apple-silicon-mlx` label hits in recent issues for a pattern — is pyannote-on-MPS a known-broken combination?

**Fix sketch (post-investigation):** Three plausible shapes — (a) pyannote dependency missing from the MLX extra path → add it or document the limitation in UI; (b) device-selection bug forcing CUDA on Apple Silicon → add MPS/CPU fallback; (c) pyannote.audio + Apple Silicon MPS is genuinely broken upstream → gate the pyannote choice with a "Linux/Windows + CUDA only" capability flag and surface a clear "use Sortformer on Mac" message in the dashboard. Choice depends on investigation outcome.

### gh-87 Wave 4 — design-conversation blur reductions (CONDITIONAL)

**User-directed entry (2026-04-25):** Severity is LOW per triage rule (these are *additional GPU headroom*, not user-visible bugs once W1–W3 ship). **Retained on the shelf per explicit user instruction during the 2026-04-25 brainstorming-session extension.** Single bundled pointer entry — full per-action detail lives in `_bmad-output/brainstorming/brainstorming-session-2026-04-20-issue-87-mac-idle-rca.md` (Phase 4, Wave 4).

**Status note (updated 2026-04-26):** E125 (user-facing toggle) shipped in commit `f138b37` — `Settings → App → Appearance → Blur effects`, default ON, OFF persisted via `ui.blurEffectsEnabled`. The E126 default-shift decision (default `--glass-fidelity: 0.5` vs `1.0`) remains in Wave 4 here, and is now the next-most-likely lever if reporter feedback says "I did not know about the toggle". Companion Cluster 1 follow-up (idle visualizer character restoration via CSS/SVG keyframes) shipped in commit `a129877`.

**Status note (updated 2026-05-31, Issue #124 investigation):** Issue #124 (M4 Max, macOS 15, v1.3.5; reporter odnodn) reports persistent idle CPU 44% / GPU 13.5% with the Sessions tab open — **trigger conditions #1 AND #2 are now both satisfied.** Investigation correction: trigger #1 below is mis-framed — it assumes Wave 3 native vibrancy *shipped and failed*, but **Wave 3 / E95 native macOS vibrancy was NEVER implemented** (grep confirms no `vibrancy`/`setVibrancy`/`backgroundMaterial` anywhere in `dashboard/electron/` or `dashboard/src/`). The highest-leverage idle-GPU lever (predicted 30–60% Mac reduction) is simply absent. Two adversarial verdicts during the #124 investigation REFUTED the theory that the idle SVG keyframes (`a129877`) are the dominant cost — they animate transform/opacity on the compositor only (no per-frame paint/JS), so **do NOT revert `a129877`**. Residual idle cost is the backdrop-blur stack itself; the shipped E125 toggle defaults ON and is buried in Settings, so this reporter got no relief. **Decision (2026-05-31, Bill):** idle resources deferred from #124's regression fix — #124's code work is scoped to the Metal-start diagnostics (`spec-gh-124-metal-start-diagnostics.md`); idle resources remain owned by this #87 Wave 4 entry. **Before scoping a fix, obtain a per-process Activity Monitor split (renderer vs GPU-helper)** — the 44% CPU is not explained by a compositor animation alone and may implicate React-Query 10s polls (`useServerStatus.ts`, `useAdminStatus.ts`).

**Status note (updated 2026-05-31, Low idle usage toggle implemented):** Per Bill's decision (evidence gate: no Apple Silicon Mac available, so scoped from the RCA residual-cost table + platform-independent code analysis, not a fresh per-process measurement), a single cross-platform **Low idle usage** toggle was implemented on branch `feat/gh-87-low-idle-usage-toggle` (spec `spec-gh-87-low-idle-usage-toggle.md`). When ON it nulls backdrop blur (the dominant idle-GPU lever — RCA "Both" row predicts ≈85–95% idle-GPU reduction) and freezes the idle visualizer waves via `data-low-idle-usage='on'`; plus an always-on `data-doc-hidden` gate that pauses idle waves while the window is hidden. Default OFF on every platform (no arch branching), and it wins over the per-effect Blur toggle by CSS precedence. Investigation also corrected two handoff facts: the RCA cites 21 files / 36 blur call-sites (not "~54"), and React-Query already pauses 10s polls when the window is hidden, so polling is NOT a plausible driver of the 44% CPU (left out of scope). Adversarial review (blind + edge + acceptance, 2026-05-31) found no CRITICAL/HIGH issues; the MEDIUM findings (settings persistence-source divergence on external localStorage wipe / partial save failure) were dropped per triage as pre-existing/inherited from the blur-toggle pattern. **Still pending:** reporter confirmation of the actual Mac CPU/GPU delta, and native macOS vibrancy (E95 — the highest-leverage Mac lever, predicted 30–60%) which remains UNIMPLEMENTED and is the next escalation if the toggle proves insufficient.

**Status note (updated 2026-06-01, E89 audit front-loaded):** Of the Wave-4 set, only **E89** (the designer audit) was addressable without an Apple Silicon Mac — it is pure static analysis that changes zero shipped pixels and needs no Mac measurement or designer assets. It shipped as `gh-87-blur-tier-audit.md` (the canonical per-surface T1–T4 decision map). The audit corrected three stale handoff facts (61 sites/21 files not 36; F1 tier vocabulary never landed in `design-language.md`; `--glass-fidelity` token does not exist) and surfaced one non-obvious blocker: the SessionView scroll-edge fades the RCA called a "free" blur drop (F4/E36) are in fact **mandated** by `design-language.md:25-29` ("Blur Bars MUST use `backdrop-blur-sm`"), so dropping them needs a design-language amendment, not a silent edit. **Everything else stays gated:** E126 needs an owner decision on the default (changes the look on all platforms, Linux primary) + ideally a Mac look-check; E95/native vibrancy can be authored as a platform-guarded skeleton but its macOS appearance is unverifiable here and the chosen posture holds it as escalation; E48/E74/E127 + E31/E32 + E59/E92 need a Mac visual sign-off and/or designer-produced assets. The audit's recorded lowest-risk first tranche (when greenlit): scrim-blur drops (E35) + small-surface drops (E60) + FullscreenVisualizer E14.

**Trigger #2 status (2026-04-26):** Issue #91 (Glitch scrolling Model Selection — Mac, darwin 15.7.5) was filed 2026-04-23 — technically satisfies trigger condition 2. However, with E125 now shipped, #91 is addressable via the user-facing opt-out. Re-triage when reporter confirms whether the toggle resolves the symptom; if not, promote E126 (default-shift) next.

**Trigger conditions (any one):**
1. Wave 3's native vibrancy + radius token does NOT close issue #87 — Mac reporter still sees idle CPU > 2% or GPU helper > 1%.
2. A new Mac/Windows GPU-related issue is filed against the dashboard.
3. Project owner decides to formalize the blur-tier design language proactively (e.g. ahead of a wider redesign).

**Wave 4 candidate set (do not implement until trigger fires):**
- **E89** — ✅ **DONE (2026-06-01, front-loaded — analysis only, no demotions executed).** Full T1–T4 classification of every blur surface → `gh-87-blur-tier-audit.md`. Corrections it bakes in: the F1 tier vocabulary was **never actually shipped** to `design-language.md` (the audit defines it); the verified surface is **61 sites / 21 files** (not 36); `--glass-fidelity` does not exist (blur is a binary on/off escape valve). Every *demotion* the audit recommends stays Mac-/decision-gated.
- **E126** — Default `--glass-fidelity: 0.5` (E125 toggle now in active sprint). Decision required: ship reduced default or full default?
- **E48 / E74 / E127** — Pre-rendered blurred PNGs per theme. Decision required: accept build-time blur philosophy?
- **E31 / E32** — Confine blur to chrome only / frosted-edge only. Decision required: major aesthetic shift accepted?
- **E59 / E92** — Platform-asymmetric glass quality (Mac full glass, Linux/Windows tinted-only). Decision required: accept platform parity loss?

**Re-triage:** when W3 ships, re-evaluate this entry. If issue #87 closes, drop. If still open, promote individual candidates to active sprint work.

### gh-101 — `hasVulkanWsl2SidecarImage` does not detect partial-pull / corrupted-layer images (LOW-MEDIUM)

**Surfaced 2026-05-02 during code review of `spec-gh-101-followup-vulkan-wsl2-comprehensive`.** `docker image inspect` returns success for an image with corrupted layers from a partial pull. Compose `up` then fails much later with an opaque whisper-server error pointing at missing files inside the container, far from the dashboard's preflight check.

**Defense shape:** Run a `docker run --rm <image> /bin/true` smoke test (or check `RepoDigests.length > 0`) after the inspect. Defer because corrupted partial pulls require an interrupted `docker pull` and the Dockerfile build path doesn't pull in pieces — for v1.3.5 every Vulkan-WSL2 user builds locally, so the failure mode is already low-likelihood.

**Re-triage trigger:** First user report of "vulkan-wsl2 starts but whisper-server crashes immediately" OR when the WSL2 sidecar gets a published GHCR tag and users start pulling it (no longer "every user builds locally").
