---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'Root Cause Analysis — Issue #101 Vulkan startup failure on Windows + AMD GPU'
session_goals: 'Identify all layers of root cause; explicitly defer fix design / planning / implementation'
selected_approach: 'ai-recommended'
techniques_used: ['5-whys-ladder', 'constraint-mapping', 'failure-mode-decomposition']
ideas_generated: ['layer-1-issue-wording', 'layer-2-hardcoded-dri-mount', 'layer-3-image-icd-mismatch', 'layer-4-architectural-assumption', 'layer-5-ux-detection-gap', 'layer-6-verification-gap', 'layer-7-issue-lifecycle-mismatch']
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Bill
**Date:** 2026-05-02

## Session Overview

**Topic:** Root Cause Analysis — Issue #101 (Can't start server with Vulkan)
**Goals:** Identify all layers of root cause for the failure that user `zrmdsxa` is still seeing on v1.3.4 (Windows 11 + RX 7700 XT). Bill wants to make AMD GPU acceleration genuinely work on Windows for v1.3.5; the v1.3.4 commit (`d3084a4`) only made the failure faster and clearer, not solved.

**Out of scope (explicit user instruction):**
- Solution design / fix proposals
- Implementation plans
- v1.3.5 roadmap

### Issue Timeline

| Version | What happened | Outcome for user |
|---|---|---|
| **v1.3.3** (issue filed) | User selected Vulkan profile on Windows + AMD; Docker daemon emitted cryptic error: `error gathering device information while adding custom device "/dev/dri": no such file or directory` | Server failed to start; root cause opaque |
| **v1.3.4** (commit `d3084a4`) | Bill added `checkVulkanSupport(platform, exists)` host-side preflight in `dashboard/electron/dockerManager.ts:130-150`. Non-Linux platforms now short-circuit before Docker is invoked, returning an actionable error. README + UI also updated to label Vulkan "Linux only". | Server still fails to start; error message is now clear instead of cryptic. **From the user's perspective: identical end state.** |
| **v1.3.4 user reply** | Screenshot shows the new gated error message verbatim | User reports "issue persists" — and they are correct. The acceptance criterion in the issue title (*"Can't start server with Vulkan"*) is still failing. |

### Why "the issue persists" is true even though commit `d3084a4` shipped

- The user's **stated bug** was the cryptic Docker daemon error.
- The user's **underlying goal** is AMD GPU acceleration on their Windows machine.
- v1.3.4 fixed the stated bug (cryptic → actionable error) but did not address the underlying goal — and the issue title (*"Can't start server with Vulkan"*) is keyed on the goal, not the error wording.
- Bill's own follow-up comment confirms this is a goal, not just a UX cleanup: *"I'm really interested in making the app work on Vulkan… so I know what to improve for v1.3.5 regarding Vulkan."*

## Technique 1 — 5-Whys Ladder

The 5-Whys ladder peels back surface symptoms to expose deeper structural causes. Each step asks "and why does *that* hold?"

**Q1.** *Why does the user see "Vulkan runtime is only supported on Linux"?*
**A1.** Because `dockerManager.ts:1997-2001` calls `checkVulkanSupport(process.platform, …)` before spinning up Compose, and the function short-circuits on `platform !== 'linux'` (lines 134-140).

**Q2.** *Why does that short-circuit exist?*
**A2.** Because before commit `d3084a4`, Compose would invoke the Docker daemon, which would then fail with a cryptic device error when it tried to apply `devices: /dev/dri:/dev/dri` from `docker-compose.vulkan.yml:67`. The new guard converts a confusing daemon error into an actionable host-side error.

**Q3.** *Why does the Docker daemon fail on `/dev/dri:/dev/dri` on Windows?*
**A3.** Because Docker Desktop on Windows runs containers inside a Linux VM (the WSL2 distro `docker-desktop`), and that VM does not have a `/dev/dri` device node. `/dev/dri` is the Linux **DRM/DRI** subsystem which is exposed only on a real Linux host kernel with an actively bound AMD/Intel GPU driver — which the WSL2 distro doesn't have.

**Q4.** *Why doesn't the WSL2 distro have a `/dev/dri` node when the Windows host has a working AMD RX 7700 XT?*
**A4.** Because WSL2 uses an **entirely different** GPU paravirtualization mechanism. Microsoft exposes the GPU into Linux via a single virtual device `/dev/dxg` plus a user-mode driver bundle mounted from the Windows host into `/usr/lib/wsl/` (Windows DirectX UMDs translated into a Linux Vulkan/D3D12 layer). It explicitly does **not** expose `/dev/dri`, because the AMD kernel-mode driver lives on the Windows side, not inside the Linux VM.

**Q5.** *Why doesn't the Vulkan profile use `/dev/dxg` instead of `/dev/dri` on Windows?*
**A5.** Because the upstream image `ghcr.io/ggml-org/whisper.cpp:main-vulkan` was built for bare-metal Linux. It links against Mesa Vulkan ICDs that look up GPUs through `/dev/dri` and won't find a usable physical device through `/dev/dxg` without the Microsoft WSL ICD bundle (`libdxcore.so` + `dxgkrnl_d3d12.so` + `dzn_icd.x86_64.json`) being mounted from `/usr/lib/wsl/`. Even if Compose mounted `/dev/dxg`, the Vulkan loader inside the container would enumerate zero devices because no WSL ICD is present.

**Q6 (bonus).** *Why was the Vulkan profile architected as "Docker sidecar with `/dev/dri` mount" in the first place?*
**A6.** Because the original feasibility study (Issue #5, prior brainstorm 2026-03-24) targeted Linux-host AMD/Intel users and used the simplest possible passthrough idiom. Cross-platform was deferred (the README originally claimed "Windows/macOS should work but are untested" — corrected to "Linux only" by `d3084a4`). The architecture quietly assumes "host kernel exposes the GPU as `/dev/dri`," which excludes WSL2 by construction.

**Ladder verdict:** The chain bottoms out at Q5/Q6 — the proximate cause is a hardcoded device path, but the structural cause is **a Linux-DRI-shaped architectural assumption baked into the sidecar contract.**

---

## Technique 2 — Constraint Mapping (Real vs Imagined)

Same frame as the prior Issue #48 RCA — separates immutable constraints from constraints that only feel immutable.

| Constraint | Real / Imagined | Notes |
|---|---|---|
| Docker Desktop on Windows uses a WSL2 Linux VM | **Real** | Architectural fact of Docker Desktop ≥ 4.x |
| WSL2 doesn't expose `/dev/dri` to its Linux kernel | **Real** | Microsoft design choice; AMD KMD lives on Windows side |
| WSL2 *does* expose `/dev/dxg` + `/usr/lib/wsl/` | **Real** | Available since Windows 10 21H2 / Windows 11 |
| Docker Desktop forwards `/dev/dxg` into containers | **Imagined as blocker** | Modern Docker Desktop **can** do GPU passthrough for WSL2; this isn't an automatic blocker, it depends on Docker Desktop version + settings |
| `whisper.cpp:main-vulkan` upstream image must work on WSL2 | **Imagined as blocker** | Could be replaced with a custom-built sidecar image that includes the WSL Vulkan ICD bundle |
| Mesa is the only Vulkan ICD path | **Imagined** | Microsoft's `dzn` (Dozen) ICD translates Vulkan→D3D12 inside WSL — explicit Microsoft-supported path |
| Vulkan must run as a *sidecar* | **Imagined** | The current architecture chose sidecar for isolation; native-Windows whisper.cpp.exe + IPC is a valid alternative shape that bypasses the WSL2 question entirely |
| User has NVIDIA hardware | **Real for this user** | RX 7700 XT — no CUDA path |
| The error message is the *bug* being reported | **Imagined** | The issue title is "Can't start server with Vulkan" — the bug is the inability to start, not the wording of the error |
| Bill cannot test AMD locally | **Real** | No AMD GPU on the dev box; verification has to come from the reporter or CI |
| Vulkan compose overlay can stay Linux-only | **Real if scope limits allow** | A second overlay (e.g. `docker-compose.vulkan-wsl2.yml`) could exist for Windows; or scope can be intentionally limited |

**Breakthrough finding from constraint mapping:** Five of the assumed-fatal constraints (rows 4, 5, 6, 7, 9) are *imagined* blockers. The real, immovable constraints are only "WSL2 is different" and "Bill has no AMD hardware." Everything else is a design choice.

---

## Technique 3 — Failure Mode Decomposition (where in the stack does the failure actually live?)

This pinpoints **which layer** is responsible by walking the start-server call from click to crash.

| Layer | Location in code | Behavior in v1.3.4 (Windows + AMD) | Is this where the root cause lives? |
|---|---|---|---|
| **L1 — Auto-detect** | `dockerManager.ts:2964` (`if (!gpu && process.platform === 'linux')`) | Vulkan detection is gated to `platform === 'linux'`; on Windows `info.vulkan = false` and auto-detect picks **CPU**, not Vulkan | No — auto-detect quietly does the right thing |
| **L2 — UI affordance** | `ServerView.tsx:1995` (`onClick={() => handleRuntimeProfileChange('vulkan')}`) | Vulkan button is **clickable** on Windows | **Partial cause** — button presence implies viability |
| **L3 — Soft warning** | `SettingsModal.tsx:685-691` | Red-text `<p>` warns "Vulkan requires Linux" | Mitigates L2 but easy to miss; Settings ≠ ServerView, user may never see it |
| **L4 — Pre-flight guard** | `dockerManager.ts:1997-2001` → `checkVulkanSupport()` (line 130) | Throws actionable error before Compose runs | This is the *current visible failure point*, but it is *correct behavior* — it's protecting the user from the deeper issue |
| **L5 — Compose overlay** | `docker-compose.vulkan.yml:66-67` (`devices: /dev/dri:/dev/dri`) | Hardcoded Linux device path | **Proximate root cause** — this is the line that can never resolve on Windows |
| **L6 — Sidecar image** | `ghcr.io/ggml-org/whisper.cpp:main-vulkan` | Built for Mesa-via-DRI; no WSL ICD bundle baked in | **Structural root cause** — even if L5 were rewritten to mount `/dev/dxg`, no Vulkan device would enumerate |
| **L7 — Compose strategy** | `dockerManager.ts:1223-1224` (push `docker-compose.vulkan.yml` for `runtimeProfile === 'vulkan'`) | Single overlay file; no platform-specific variant | Structural — there's no separate WSL2 overlay to layer on Windows |
| **L8 — Project policy** | README §2.5 + Issue #5 feasibility study | "Linux only" policy as of d3084a4 | **Honest** — but the policy contradicts the UI affordance at L2 |

**Failure-mode verdict:** The user-visible failure is at L4, but **L4 is not the bug** — it's a guard correctly catching a problem that lives at L5/L6/L7. L4 is doing its job. L2 and L8 are *misaligned with each other*: L2 lets the user pick Vulkan as if it were a viable Windows option; L8 says it isn't. L5/L6/L7 make L8 true today.

---

## Synthesized Root Cause Tree

```
Issue #101 — User on Windows + AMD GPU cannot start server with Vulkan
│
├── PROXIMATE CAUSE (what the user sees)
│   └── L4: checkVulkanSupport() rejects non-Linux with "Vulkan only on Linux"
│       (intentionally added in d3084a4 to replace a cryptic daemon error)
│
├── STRUCTURAL CAUSES (why L4 has to do that)
│   ├── L5: docker-compose.vulkan.yml hardcodes  devices: /dev/dri:/dev/dri
│   │       — Linux DRM/DRI device path that doesn't exist in WSL2 distro
│   │
│   ├── L6: ghcr.io/ggml-org/whisper.cpp:main-vulkan image is built against
│   │       Mesa Vulkan ICDs that look up GPUs through /dev/dri.
│   │       Doesn't ship the WSL2 user-mode driver bundle (libdxcore.so,
│   │       dzn_icd.x86_64.json) needed for /dev/dxg paravirtualization.
│   │
│   └── L7: Single Compose overlay ("vulkan profile" = one file).
│           No platform-specific variant for Windows-WSL2 path.
│
├── UX/PRODUCT CAUSES (why the user got into this state at all)
│   ├── L2: Vulkan button is clickable on Windows in ServerView.tsx,
│   │       even though the Linux-only constraint is real.
│   │       (Soft warning lives in SettingsModal, not next to the button.)
│   │
│   └── L8: "Linux only" policy (post-d3084a4) contradicts L2 affordance
│           — the README says one thing, the ServerView button says another.
│
├── VERIFICATION CAUSES (why the bug ships and lingers)
│   ├── L9: Bill has no AMD GPU hardware → no local repro for any
│   │       Vulkan path, Linux or otherwise.
│   │
│   └── L10: No CI matrix exercises Windows + Vulkan profile end-to-end.
│            Every Windows + AMD user is the de facto integration tester.
│
└── ISSUE-LIFECYCLE CAUSE (why "fixed" ≠ "resolved")
    └── L11: Issue title "Can't start server with Vulkan" keys on the
             *outcome* (server doesn't start). d3084a4 changed the
             *error wording* but not the outcome — so by the title's
             own acceptance criterion, the issue is genuinely still open.
```

---

## What "the root cause" actually means here (one-paragraph summary)

The proximate cause of the error message is the Linux-only guard added in `d3084a4` (correctly catching a deeper problem). The proximate cause the guard is protecting against is the hardcoded `/dev/dri:/dev/dri` device mount in `docker-compose.vulkan.yml`. The structural cause is that the entire Vulkan profile architecture — sidecar image + device mount — was designed around a Linux-host DRI-passthrough idiom that doesn't generalise to Docker Desktop on Windows, where GPU paravirtualization runs through `/dev/dxg` plus a Microsoft user-mode driver bundle that the upstream `whisper.cpp:main-vulkan` image doesn't include. A UX gap (clickable Vulkan button vs. soft warning in a different modal) lets Windows users select a profile that the architecture cannot serve, and the verification gap (no AMD test bench, no CI matrix) means the misalignment shipped without anyone catching it. The issue feels "still open" to the reporter because the issue title ("Can't start server with Vulkan") describes the *outcome*, not the error wording — and the outcome is unchanged.

---

## Verification of WSL2 GPU paravirtualization claims (2026-05-02)

The structural-cause section above made several claims about WSL2 internals that were originally flagged as "general-knowledge inference, worth confirming." User asked for confirmation before moving on. Results:

| # | Claim | Source | Verdict |
|---|---|---|---|
| 1 | WSL2 exposes the GPU to Linux via `/dev/dxg` (the dxgkrnl driver) | Microsoft DirectX team blog (devblogs.microsoft.com/directx/directx-heart-linux): *"Dxgkrnl is a brand-new kernel driver for Linux that exposes the **/dev/dxg** device to user mode Linux."* | **Confirmed verbatim** |
| 2 | Windows user-mode driver libraries (libd3d12.so, libdxcore.so) are bind-mounted into the WSL2 distro at `/usr/lib/wsl/lib` | Same Microsoft blog: *"libd3d12.so and libdxcore.so are closed source, pre-compiled user mode binaries that ship as part of Windows...automatically mounted under /usr/lib/wsl/lib"* | **Confirmed verbatim** |
| 3 | Vulkan on WSL2 goes through Mesa's `dzn` (Dozen) Vulkan→D3D12 translation driver | Microsoft blog explicitly **defers Vulkan**: *"What about Vulkan? We are still exploring how best to support Vulkan in WSL and will share more details in the future."* WebSearch surfaced active community reports (e.g. NVIDIA Developer Forums *"Vulkan Fails to Detect NVIDIA GPU on WSL2 Ubuntu 24.04 — `dzn` Driver Files Missing"*; ollama/ollama#14854; microsoft/wslg#40, #1254) all keyed on `dzn` as the expected Vulkan ICD path on WSL2. | **Partially confirmed** — `dzn` is the de facto path used by the community / Mesa, but Microsoft has not formally documented or endorsed it as the supported path. |
| 4 | The upstream `ghcr.io/ggml-org/whisper.cpp:main-vulkan` image is built for bare-metal Linux Mesa Vulkan and does **not** include any WSL-specific setup | `whisper.cpp/.devops/main-vulkan.Dockerfile` (master branch): `FROM ubuntu:24.04`; build stage installs `libvulkan-dev glslc`; runtime stage installs `libvulkan1 mesa-vulkan-drivers`. No references to WSL, dxg, dxcore, dzn, `/usr/lib/wsl/`, or `/dev/dri`. | **Confirmed by reading the actual Dockerfile.** The image will pick up whatever the host kernel exposes through Mesa's standard ICD search path. On bare-metal Linux that's radv via `/dev/dri`; in a WSL2 distro that mounts `/usr/lib/wsl/lib` and `/dev/dxg`, recent Mesa packages *can* expose dzn — but the upstream image does not configure any of the runtime environment (mounts, env vars, etc.) that this requires. |

### Corrections vs. the original claim
- Slight over-specification in original claim: I wrote that the WSL ICD bundle includes `dzn_icd.x86_64.json`. **Refinement:** the Microsoft-side bundle in `/usr/lib/wsl/lib` ships `libd3d12.so` + `libdxcore.so` only. The Mesa-side `dzn` Vulkan ICD (manifest typically `dzn_icd.x86_64.json`) is provided by the **Mesa package** in the Linux distro — it depends on `libd3d12.so` from `/usr/lib/wsl/lib` at runtime. So the dependency chain inside a WSL2 container is: `/dev/dxg` (kernel) ← `libd3d12.so` (Microsoft, mounted) ← `dzn` ICD (Mesa, installed) ← Vulkan loader.
- The whisper.cpp:main-vulkan image's `mesa-vulkan-drivers` package (Mesa 23+ on Ubuntu 24.04) **may** include `dzn` in the package contents, but the Dockerfile does not mount `/dev/dxg`, does not bind `/usr/lib/wsl/lib`, and does not set the env vars (e.g. `LD_LIBRARY_PATH`, `VK_ICD_FILENAMES`) required for the Vulkan loader to find dzn. So the structural conclusion stands: **even if Compose passed `/dev/dxg` instead of `/dev/dri`, the upstream image's Vulkan loader would enumerate zero devices on WSL2 without additional container plumbing.**

### Sources
- [DirectX ❤ Linux — Microsoft DirectX Developer Blog](https://devblogs.microsoft.com/directx/directx-heart-linux/) (canonical primary source for `/dev/dxg` and `/usr/lib/wsl/lib`)
- [whisper.cpp main-vulkan.Dockerfile (master)](https://github.com/ggml-org/whisper.cpp/blob/master/.devops/main-vulkan.Dockerfile) (read directly; no WSL components)
- [Vulkan Fails to Detect NVIDIA GPU on WSL2 Ubuntu 24.04 — `dzn` Driver Files Missing — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/vulkan-fails-to-detect-nvidia-gpu-on-wsl2-ubuntu-24-04-dzn-driver-files-missing-tested-on-multiple-systems/342142) (community evidence that dzn is the expected path and is fragile in practice)
- [WSL2 + Intel Arc 140T: Vulkan runner hangs on `/dev/dxg` — ollama/ollama#14854](https://github.com/ollama/ollama/issues/14854) (peer-project hitting the same architectural seam)
- [Vulkan support in WSL2/WSLg — microsoft/wslg#1254](https://github.com/microsoft/wslg/issues/1254) and [Add support for Vulkan — microsoft/wslg#40](https://github.com/microsoft/wslg/issues/40) (long-running upstream issues; Vulkan-on-WSL2 still not first-class)
- [Hardware-accelerated vulkan in WSL2 — microsoft/WSL#7790](https://github.com/microsoft/WSL/issues/7790)
- [Windows Subsystem for Linux Graphics Architecture (XDC slides, PDF)](https://lpc.events/event/9/contributions/610/attachments/700/1295/XDC_-_WSL_Graphics_Architecture.pdf)

### Net effect on the root-cause analysis
- Layer 5 (hardcoded `/dev/dri`) — claim unchanged.
- Layer 6 (image-level constraint) — **strengthened**, not weakened. The image really is bare-metal-Linux-shaped (Dockerfile read directly).
- The WSL2 alternative path (`/dev/dxg` + `/usr/lib/wsl/lib` + Mesa `dzn`) is **a real path that Microsoft and Mesa support architecturally**, but it is **not a polished, drop-in replacement**: open issues remain in microsoft/wslg, peer projects (Ollama) hit the same seams, and the upstream whisper.cpp image is not built for it. So the structural-cause framing in the tree is correct; just be precise that "WSL2 has no GPU passthrough" would be wrong — "WSL2 GPU passthrough exists but uses a fundamentally different stack the current sidecar image is not built for" is right.

---

## Out-of-Scope (per user instruction)

- Fix proposals (sidecar redesign, native-Windows whisper.cpp, DirectML alternative, WSL2 overlay file, etc.)
- v1.3.5 implementation plan
- Whether to mark the issue *won't fix* vs. *expand-scope*
- Issue triage / labels / milestones

These will be the subject of a follow-up planning session once root cause is agreed.
