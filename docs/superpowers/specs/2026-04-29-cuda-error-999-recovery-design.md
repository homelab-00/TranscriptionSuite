# Design — CUDA Error 999 Diagnosis & In-App GPU Health

**Date:** 2026-04-29
**Status:** Draft (pending implementation plan)
**Topic:** Diagnose and harden the project against the recurring "CUDA unknown error / error 999" Docker GPU initialization failure that surfaces in the dashboard as *"Please restart your computer to reset the GPU."*

---

## 1. Problem statement

When the unified server container starts, `torch.cuda.init()` in `server/backend/core/audio_utils.py:cuda_health_check()` intermittently raises:

```
RuntimeError: CUDA unknown error - this may be due to an incorrectly set up environment,
e.g. changing env variable CUDA_VISIBLE_DEVICES after program start.
Setting the available devices to be zero.
```

This is CUDA error code 999 (`cudaErrorUnknown`). Existing retry logic (1s/2s/4s exponential backoff, three attempts) catches transient cases. When all three retries fail, the server marks the GPU `_cuda_probe_failed = True` and falls back to CPU transcription.

In one observed failure case (host: Arch Linux, Zen kernel 6.19.14, NVIDIA driver 595.58.03, RTX 3060, PyTorch cu129), the standard remediations all failed:

- Host reboot
- Fresh Docker image rebuild
- Deletion of the `transcriptionsuite-runtime` volume

`nvidia-smi` continued to succeed on the host throughout. The container could not initialize CUDA. CPU fallback works but is too slow to be useful for non-trivial transcription on a 12 GB-class GPU.

This design covers two phases:

- **Phase 1** — A reusable host-side diagnostic that captures the structural signals needed to identify the actual root cause from a small set of well-documented candidates, plus the host fix to apply once identified.
- **Phase 2** — Modest in-app changes (backend hint message + dashboard preflight + Server-tab GPU Health card) so future occurrences self-diagnose at startup and the user never sees the misleading "restart your computer" instruction without an explanation.

Out-of-scope intentionally: any path that runs `sudo`/`pkexec` from the dashboard, automatic retry-after-N-seconds, per-distro fix recipes beyond generic NVIDIA-doc commands.

---

## 2. Background — why error 999 happens (research summary)

The PyTorch warning text always blames `CUDA_VISIBLE_DEVICES`, but error 999 is the driver's generic "I cannot enumerate any GPU." Documented candidate root causes for this failure mode in containerized PyTorch on Linux, in order of likelihood for a system that previously worked and where `nvidia-smi` succeeds on the host:

1. **Missing `/dev/char` symlinks for NVIDIA devices** — recent `runc` requires `/dev/char/<major>:<minor>` symlinks for every device node injected into a container; the NVIDIA driver does not create them. On systems with the systemd cgroup driver (Arch default), any `systemctl daemon-reload` (which `pacman` invokes after most package updates) revokes GPU access from running containers and breaks new-container startup.
   - Fix: `sudo nvidia-ctk system create-dev-char-symlinks --create-all` plus persistent udev rule at `/lib/udev/rules.d/71-nvidia-dev-char.rules`.
   - References: [NVIDIA Container Toolkit Troubleshooting](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html), [NVIDIA/nvidia-container-toolkit#48](https://github.com/NVIDIA/nvidia-container-toolkit/issues/48).

2. **Stale CDI spec at `/etc/cdi/nvidia.yaml`** — the spec is a static snapshot of driver state; after a driver update it advertises stale library paths and an outdated NVRM version, causing CDI injection to silently produce a broken container.
   - Fix: `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`.

3. **`nvidia_uvm` kernel module not loaded** — classic suspend-resume bug; also occurs after `nvidia-utils` package updates without module reload. `nvidia-smi` does not load `nvidia_uvm` (only CUDA does), so it can succeed while CUDA fails.
   - Fix: `sudo rmmod nvidia_uvm && sudo modprobe nvidia_uvm`. Sometimes flaky, in which case driver reinstall is needed.
   - Reference: [PyTorch issue #115340](https://github.com/pytorch/pytorch/issues/115340), [PyTorch forums thread](https://discuss.pytorch.org/t/cuda-runtime-error-999/69658/12).

4. **Docker `cgroupdriver` mismatch** — `native.cgroupdriver=systemd` (Arch default for newer Docker) makes GPU access fragile. NVIDIA documents `cgroupfs` as the safer choice for GPU workloads.
   - Fix: set `"exec-opts": ["native.cgroupdriver=cgroupfs"]` in `/etc/docker/daemon.json`, then `systemctl restart docker`.

5. **PyTorch wheel / driver mismatch** — lowest priority; CUDA 12.9 wheels with a 13.x-capable driver are forward-compatible in practice.

The dashboard already auto-detects CDI vs legacy nvidia-runtime mode in `dashboard/electron/dockerManager.ts:detectGpuMode()` (line ~2508) and selects `docker-compose.gpu-cdi.yml` or `docker-compose.gpu.yml` accordingly. Both paths are vulnerable to candidates 1, 3, and 4; only the CDI path is vulnerable to candidate 2.

---

## 3. Phase 1 — Host diagnostic + host fix

### 3.1 Deliverable

A self-contained shell script `scripts/diagnose-gpu.sh` (committed to the repository), plus a companion `scripts/README-gpu-diagnostic.md` documenting what each check measures and the recommended remediation for each failure mode.

The script is **observation-only** — no `sudo`, no mutations, no package operations. Output is written to both stdout and a timestamped log file (`gpu-diagnostic-<UTC-timestamp>.log` in the current directory) so it can be pasted back without loss.

### 3.2 Checks (in order)

| # | Check | Purpose |
|---|---|---|
| 1 | `uname -r`, `cat /etc/os-release`, NVIDIA driver version from `nvidia-smi` | Baseline host identification. |
| 2 | `nvidia-ctk --version`, `nvidia-container-cli --version` | Container-toolkit installed and ≥ 1.14 (CDI required). |
| 3 | `ls -la /etc/cdi/nvidia.yaml`, `nvidia-ctk cdi list` | CDI spec exists; what devices it advertises. |
| 4 | mtime of `/etc/cdi/nvidia.yaml` vs mtime of `/usr/lib/modules/$(uname -r)/extramodules/nvidia.ko.zst` (or distro equivalent) | CDI spec drift after driver update — root cause #2. |
| 5 | `ls -la /dev/char \| grep -E 'nvidia\|195:'` | `/dev/char` symlinks present — root cause #1. |
| 6 | `lsmod \| grep -E '^nvidia'` | `nvidia`, `nvidia_modeset`, `nvidia_uvm`, `nvidia_drm` all loaded — root cause #3. |
| 7 | `cat /etc/docker/daemon.json` (if present); `cat /etc/nvidia-container-runtime/config.toml` (if present) | Cgroup driver, `no-cgroups`, registered runtimes — root cause #4. |
| 8 | `docker info --format '{{json .}}'`, filtered to `Runtimes`, `CgroupDriver`, `DefaultRuntime` | What Docker uses at runtime. |
| 9 | Smoke test: `docker run --rm --gpus all <small NVIDIA base image> nvidia-smi` (illustrative tag: `nvidia/cuda:12.6.0-base-ubuntu24.04`; implementation picks a stable, small, currently-published tag) | Isolates host-side breakage (test fails) from project-specific issues (test passes). |
| 10 | If smoke passes: same image, `bash -c "ls /dev/nvidia* && cat /proc/driver/nvidia/version"` | Container actually sees NVIDIA proc files. |
| 11 | PASS / WARN / FAIL summary block | Quick-read at the end. |

### 3.3 Decision tree (output → fix)

```
Smoke test (#9) FAIL
├── /dev/char NVIDIA symlinks missing (#5)        → sudo nvidia-ctk system create-dev-char-symlinks --create-all
│                                                    plus udev rule for persistence
├── CDI spec stale (#4) or missing (#3)           → sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
├── nvidia_uvm not in lsmod (#6)                  → sudo rmmod nvidia_uvm && sudo modprobe nvidia_uvm
│                                                    if fails: driver reinstall
├── Docker cgroup driver = systemd (#7, #8)       → /etc/docker/daemon.json native.cgroupdriver=cgroupfs
└── (none of above match)                         → escalate; capture full container logs

Smoke test (#9) PASS
└── Issue is project-internal                     → inspect /runtime/.venv, PyTorch wheels, LD_LIBRARY_PATH
                                                    inside the actual container
```

### 3.4 Companion README content

The companion `scripts/README-gpu-diagnostic.md` covers:

- What the script does and what it does *not* do (no mutations, no sudo).
- How to run it: `bash scripts/diagnose-gpu.sh > gpu-diagnostic.log 2>&1`.
- A table mapping each check number to (a) what failure looks like in the log and (b) the canonical fix command from NVIDIA documentation.
- Links to the NVIDIA Container Toolkit troubleshooting page and the GitHub issues referenced in §2.
- Platform note: script is Linux-only; on macOS/Windows it should print a friendly "this diagnostic is for Linux NVIDIA installs only" message and exit 0.

### 3.5 Acceptance criteria for Phase 1

- Script runs end-to-end on Arch with no errors when all checks pass (healthy GPU host).
- Script produces clear `FAIL: <check>` lines when each individual check is artificially broken.
- Smoke test (#9) tolerates a missing/unpullable image: prints WARN with the pull command, does not crash.
- README enables a new user to read the log and find the fix without external help in the four documented failure modes.

---

## 4. Phase 2 — App-side hardening

### 4.1 Backend — `recovery_hint` in CUDA health result

**File:** `server/backend/core/audio_utils.py`

`cuda_health_check()` already returns a dict with `status`, `error`, `nvidia_smi`. Add an optional `recovery_hint: str | None` field, populated only when `status == "unrecoverable"` and the error string matches the error-999 fingerprint (`"unknown error" in err_lower or "error 999" in err_lower`).

The hint is one short line, host-platform-aware where the platform is detectable inside the container (Linux always; we can read `/etc/os-release` from the container's view of the host root, but in practice the container *is* on Linux when this code runs):

```python
recovery_hint = (
    "GPU init failed with error 999 (CUDA unknown). This is almost always "
    "host-side: missing /dev/char symlinks, stale CDI spec, or nvidia_uvm "
    "not loaded. Run scripts/diagnose-gpu.sh on the host for details."
)
```

The hint surfaces through whatever endpoint already exposes `cuda_health_check` results to the dashboard (the existing `/health` or admin status routes already include CUDA status).

**Change scope:** ~10 lines + 1 unit test for the heuristic.

### 4.2 Dashboard preflight — `validateGpuPreflight()`

**File:** `dashboard/electron/dockerManager.ts`

Add `validateGpuPreflight()` that runs after `detectGpuMode()` (~line 2510) and returns a structured result. Only the *cheap* subset of the script's checks runs at preflight (no `docker pull`, no container run):

| Check | Implementation | Failure surface |
|---|---|---|
| CDI spec exists | `fs.existsSync('/etc/cdi/nvidia.yaml')` | Yellow |
| CDI spec mtime newer than driver install | compare to `/usr/lib/modules/$(uname -r)/...` mtime via `stat` | Yellow |
| `/dev/char` NVIDIA symlinks | `fs.readdirSync('/dev/char')` filtered for `195:*` | Yellow |
| `nvidia_uvm` loaded | shell out to `lsmod \| grep -q nvidia_uvm` | Yellow |

Result shape (typed):

```typescript
interface GpuPreflightResult {
  status: 'healthy' | 'warning' | 'unknown';
  checks: Array<{
    name: string;
    pass: boolean;
    fixCommand?: string;
    docsUrl?: string;
  }>;
}
```

**Platform gating:** `validateGpuPreflight()` returns `{ status: 'unknown', checks: [] }` immediately when `process.platform !== 'linux'` or when `detectGpuMode()` returned `null` (no NVIDIA GPU detected). All checks are no-ops outside the Linux + NVIDIA happy path.

**Change scope:** ~80 lines + a unit test mirroring the existing `dockerManager` test layout (`dashboard/electron/__tests__/`).

### 4.3 Dashboard UI — GPU Health card on the Server tab

**File:** `dashboard/components/views/ServerView.tsx`

A new card, placed in the existing system-status area of `ServerView.tsx`. The card is **rendered only when an NVIDIA GPU is detected** (`cachedGpuInfo.gpu === true`). On Apple Silicon / AMD / Intel-only systems the card does not appear at all, removing any chance of confusing a non-NVIDIA user.

When rendered, the card displays a top-line label that explicitly scopes it: **"GPU Health (NVIDIA)"**.

Three states:

- **Green — "GPU healthy — CUDA operational"** when all preflight checks pass *and* the most recent backend health probe reported `status: healthy`.
- **Yellow — "GPU may be misconfigured"** when one or more preflight checks fail but the backend has not yet reported an error. Each failed check renders a row with: short description, the documented fix command in a copyable `<code>` block, and a "More info" link to NVIDIA docs.
- **Red — "GPU unavailable — fell back to CPU"** when the backend reported `status: unrecoverable`. The `recovery_hint` from §4.1 is shown verbatim. Below it: the same fix-command rows from the yellow state for any check that is currently failing.

Below the state block: a **"Run Full Diagnostic"** button. Clicking it:
- On Linux: invokes the diagnostic script and surfaces the log path. The script must be reachable from both a source checkout (`<repo>/scripts/diagnose-gpu.sh`) *and* a packaged Electron app — the implementation plan will decide whether to bundle it as an `extraResource` at build time or fall back to printing the path/command to a copy-paste modal when the script is not bundled (e.g. dev builds without the bundling step).
- On non-Linux NVIDIA setups (theoretically WSL2): shows the literal command to run in a copy-paste modal, no auto-execute.

The card includes a single explanatory line near the title:

> *"This card appears only on systems with an NVIDIA GPU. AMD / Intel / Apple Silicon setups do not need it."*

**Change scope:** ~150 lines for the card component + integration in `ServerView.tsx`. A snapshot test or render test covering green/yellow/red states.

### 4.4 Cross-platform handling

| Platform | Card shown? | Behaviour |
|---|---|---|
| Linux + NVIDIA | Yes | Full preflight + Run Diagnostic button. |
| Linux + AMD/Intel (Vulkan path) | No | Card hidden. Vulkan health surfaced through existing Vulkan profile UI. |
| Linux + no GPU | No | Card hidden. |
| Windows | Stub card | "GPU preflight is Linux-only; ensure WSL2 NVIDIA support is configured." Plus docs link. No checks run. |
| macOS | No | Card hidden entirely. The macOS path uses MLX bare-metal, not Docker CUDA. |

### 4.5 Acceptance criteria for Phase 2

- Backend: when `cuda_health_check` returns `unrecoverable` with an error-999 string, the result dict includes a non-empty `recovery_hint`.
- Backend: unit test asserts the heuristic does not produce a hint for non-error-999 failures.
- Dashboard: `validateGpuPreflight()` returns `status: 'unknown'` on macOS and Windows without invoking any host commands.
- Dashboard: on a healthy Linux+NVIDIA host, the card renders green with all checks passing.
- Dashboard: when `/dev/char` NVIDIA symlinks are deleted (simulated), the card renders yellow with the correct fix command shown.
- Dashboard: when the backend reports `unrecoverable`, the card renders red with the `recovery_hint` text visible.
- Dashboard: card is not rendered on a system reporting no NVIDIA GPU.
- "Run Full Diagnostic" button executes the script and surfaces the log path.

---

## 5. Explicitly out of scope

| Idea | Why not |
|---|---|
| One-click `pkexec nvidia-ctk cdi generate` button in the dashboard | Touches host root from a GUI app; one wrong call rewrites system config. The dashboard remains an *advisor* about the host, not an *agent* that mutates it. |
| Automatic retry-after-N-seconds with optimistic restart of the container | The existing 3-attempt 1s/2s/4s retry already covers transient cases. Adding more retries papers over structural bugs. |
| Per-distro fix recipes (Arch / Ubuntu / Fedora / NixOS-specific commands in the UI) | Generic NVIDIA-doc commands cover all distros for the four documented root causes. Per-distro hints can be added later if a real user asks. |
| Backend auto-recovery (e.g. exec into host to reload nvidia_uvm) | Container has no host root. Even with privileged mode this would be a security regression. |
| Replacing the existing `_cuda_probe_failed` flag mechanism | Out of scope; the existing CPU fallback works correctly and is not the subject of this design. |

---

## 6. Risks & open questions

- **Smoke-test image pull cost.** The diagnostic script's step #9 pulls `nvidia/cuda:12.6.0-base-ubuntu24.04` (~150 MB) the first time. Mitigation: print a one-line warning before attempting the pull, and skip with a WARN if the user has no internet. Acceptable for a one-shot diagnostic.
- **CDI spec mtime comparison heuristic.** Comparing `/etc/cdi/nvidia.yaml` mtime to driver-install mtime requires guessing the right driver path (`/usr/lib/modules/$(uname -r)/...`, or `/lib/modules/...`, or distro-specific). The check should be conservative: if the driver path cannot be located, skip the check rather than warn falsely.
- **Card placement on the Server tab.** `ServerView.tsx` is large; we should pick a location that does not push existing controls below the fold. Final placement to be confirmed during implementation.
- **`Run Full Diagnostic` UX on Linux without a default terminal app.** Some headless or minimal Linux setups have no `x-terminal-emulator`. The fallback should be: write the log path and command to a modal that the user can copy-paste into their own terminal.

---

## 7. Sequencing

Phase 1 ships first and is self-contained — script + README, no app changes, no test infrastructure changes. The user runs it once, fixes the host, and the immediate problem is resolved.

Phase 2 ships as a follow-up. The preflight checks in §4.2 are derived directly from the script's checks in §3.2 — Phase 1 is the *spec* for Phase 2's preflight. This means Phase 1 work is not throwaway: it both unblocks the user *and* validates which checks are worth promoting into the dashboard.

---

## 8. References

- [NVIDIA Container Toolkit Troubleshooting](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html)
- [NVIDIA/nvidia-container-toolkit Issue #48 — Containers losing access to GPUs](https://github.com/NVIDIA/nvidia-container-toolkit/issues/48)
- [Arch Linux forum — Docker with GPU NVML Unknown Error](https://bbs.archlinux.org/viewtopic.php?id=266915)
- [PyTorch issue #115340 — modprobe reload isn't always enough](https://github.com/pytorch/pytorch/issues/115340)
- [PyTorch forums — CUDA initialization unknown error](https://discuss.pytorch.org/t/userwarning-cuda-initialization-cuda-unknown-error-this-may-be-due-to-an-incorrectly-set-up-environment-e-g-changing-env-variable-cuda-visible-devices-after-program-start-setting-the-available-devices-to-be-zero/129335)
- [PyTorch forums — `rmmod nvidia_uvm` workaround](https://discuss.pytorch.org/t/cuda-runtime-error-999/69658/12)
- Internal: `server/backend/core/audio_utils.py:cuda_health_check()` (existing retry logic)
- Internal: `dashboard/electron/dockerManager.ts:detectGpuMode()` (existing CDI/legacy detection)
- Internal: `server/docker/docker-compose.gpu.yml` and `server/docker/docker-compose.gpu-cdi.yml` (the two GPU runtime overlays)
