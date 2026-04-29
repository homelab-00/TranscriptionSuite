# CUDA Error 999 Diagnosis & GPU Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose the recurring "CUDA unknown error / error 999" Docker GPU init failure with a host-side script, and add an in-app NVIDIA-only "GPU Health" card on the Server tab so future occurrences self-explain instead of producing the misleading "Please restart your computer" message.

**Architecture:** Two phases. Phase 1 ships a self-contained, observation-only bash diagnostic (`scripts/diagnose-gpu.sh`) plus README — no project code touched, no `sudo`. Phase 2 adds (a) a `recovery_hint` field to `cuda_health_check()` so the backend tells the dashboard *what* probably broke, (b) a pure `validateGpuPreflight()` function in `dockerManager.ts` that runs cheap host checks, exposed over IPC, and (c) an NVIDIA-only `GpuHealthCard` rendered on `ServerView.tsx` with a "Run Full Diagnostic" button that invokes the Phase 1 script. No `pkexec`, no auto-fix, no per-distro recipes.

**Tech Stack:** Bash 5+, Python 3.13 / pytest, TypeScript / Vitest, React 18 / @testing-library/react, Electron IPC. Tests follow existing patterns in `server/backend/tests/` and `dashboard/electron/__tests__/`.

**Spec:** [`docs/superpowers/specs/2026-04-29-cuda-error-999-recovery-design.md`](../specs/2026-04-29-cuda-error-999-recovery-design.md)

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `scripts/diagnose-gpu.sh` | new | Bash diagnostic, 11 checks, observation-only, writes timestamped log. |
| `scripts/README-gpu-diagnostic.md` | new | Companion docs: what each check measures, fix command per failure mode. |
| `server/backend/core/audio_utils.py` | modify | Add `recovery_hint` field to `cuda_health_check()` result for error-999 unrecoverable case. |
| `server/backend/tests/test_audio_utils.py` | modify | Add `TestRecoveryHint` covering hint presence/absence per error class. |
| `server/backend/api/main.py` | modify | Surface `recovery_hint` in lifespan log + `app.state.gpu_error`. |
| `dashboard/electron/dockerManager.ts` | modify | Add pure `validateGpuPreflight(platform, fsExists, readDir, statMtime, lsmodOutput)` function + `GpuPreflightResult` type. |
| `dashboard/electron/__tests__/dockerManagerGpuPreflight.test.ts` | new | Unit tests for `validateGpuPreflight` mirroring `dockerManagerVulkanPreflight.test.ts` pattern. |
| `dashboard/electron/main.ts` | modify | Add `docker:validateGpuPreflight` and `docker:runGpuDiagnostic` IPC handlers. |
| `dashboard/electron/preload.ts` | modify | Expose `docker.validateGpuPreflight()` and `docker.runGpuDiagnostic()` plus their TS types. |
| `dashboard/package.json` | modify | Add `scripts/diagnose-gpu.sh` to `extraResources`. |
| `dashboard/components/views/GpuHealthCard.tsx` | new | React component — three states (green / yellow / red), copyable fix commands, "Run Full Diagnostic" button. |
| `dashboard/components/views/__tests__/GpuHealthCard.test.tsx` | new | Render tests for each card state. |
| `dashboard/components/views/ServerView.tsx` | modify | Mount `<GpuHealthCard />` gated on `gpuInfo.gpu === true && process.platform === 'linux'`. |

---

# Phase 1 — Host Diagnostic

## Task 1: Create `scripts/diagnose-gpu.sh`

**Files:**
- Create: `scripts/diagnose-gpu.sh`

- [ ] **Step 1: Create the script**

```bash
mkdir -p scripts
```

Then create `scripts/diagnose-gpu.sh` with the following content:

```bash
#!/usr/bin/env bash
# diagnose-gpu.sh — observation-only host diagnostic for the recurring
# "CUDA unknown error / error 999" Docker GPU initialization failure.
#
# Usage:
#   bash scripts/diagnose-gpu.sh
#   bash scripts/diagnose-gpu.sh > my-log.txt 2>&1
#
# Writes both to stdout and to ./gpu-diagnostic-<UTC-timestamp>.log so the
# output can be pasted back without loss.
#
# Performs 11 read-only checks (no sudo, no mutations, no package operations)
# and prints PASS / WARN / FAIL for each. See scripts/README-gpu-diagnostic.md
# for the fix corresponding to each FAIL.

set -u

# ── Setup ─────────────────────────────────────────────────────────────────
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
LOGFILE="gpu-diagnostic-${TIMESTAMP}.log"
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

# Tee everything to the log file from this point on.
exec > >(tee -a "$LOGFILE") 2>&1

print_header() {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

print_check() {
  # $1 = check number, $2 = title, $3 = status (PASS|WARN|FAIL|INFO), $4 = detail
  local num="$1" title="$2" status="$3" detail="$4"
  printf '[%s] #%-2s %-50s %s\n' "$status" "$num" "$title" "$detail"
  case "$status" in
    PASS) PASS_COUNT=$((PASS_COUNT + 1));;
    WARN) WARN_COUNT=$((WARN_COUNT + 1));;
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1));;
  esac
}

# ── Linux gate ────────────────────────────────────────────────────────────
if [ "$(uname -s)" != "Linux" ]; then
  echo "diagnose-gpu.sh is for Linux NVIDIA installs only."
  echo "Detected: $(uname -s). Exiting cleanly."
  exit 0
fi

print_header "TranscriptionSuite GPU Diagnostic — ${TIMESTAMP}"
echo "Log file: $LOGFILE"

# ── #1 baseline ───────────────────────────────────────────────────────────
print_header "#1 Host baseline"
echo "Kernel: $(uname -r)"
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "Distro: ${PRETTY_NAME:-unknown}"
fi
DRIVER_VERSION=""
if command -v nvidia-smi >/dev/null 2>&1; then
  DRIVER_VERSION="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || true)"
  echo "NVIDIA driver: ${DRIVER_VERSION:-unknown}"
  print_check 1 "nvidia-smi present" PASS "driver=${DRIVER_VERSION:-unknown}"
else
  print_check 1 "nvidia-smi present" FAIL "nvidia-smi not in PATH — install NVIDIA driver first"
fi

# ── #2 nvidia-container-toolkit ──────────────────────────────────────────
print_header "#2 NVIDIA Container Toolkit"
if command -v nvidia-ctk >/dev/null 2>&1; then
  CTK_VERSION="$(nvidia-ctk --version 2>/dev/null | head -n1 || true)"
  print_check 2 "nvidia-ctk installed" PASS "${CTK_VERSION:-unknown version}"
else
  print_check 2 "nvidia-ctk installed" FAIL "nvidia-container-toolkit not installed"
fi
if command -v nvidia-container-cli >/dev/null 2>&1; then
  CLI_VERSION="$(nvidia-container-cli --version 2>/dev/null | head -n1 || true)"
  echo "nvidia-container-cli: ${CLI_VERSION:-unknown}"
fi

# ── #3 CDI spec exists ───────────────────────────────────────────────────
print_header "#3 CDI spec presence"
CDI_PATH="/etc/cdi/nvidia.yaml"
if [ -f "$CDI_PATH" ]; then
  CDI_SIZE="$(stat -c '%s' "$CDI_PATH" 2>/dev/null || echo '?')"
  CDI_MTIME="$(stat -c '%y' "$CDI_PATH" 2>/dev/null || echo '?')"
  print_check 3 "CDI spec at $CDI_PATH" PASS "size=${CDI_SIZE}B mtime=${CDI_MTIME}"
  if command -v nvidia-ctk >/dev/null 2>&1; then
    echo "--- nvidia-ctk cdi list ---"
    nvidia-ctk cdi list 2>&1 || true
    echo "---------------------------"
  fi
else
  print_check 3 "CDI spec at $CDI_PATH" WARN "missing — only matters if dashboard selected CDI mode (regenerate with: sudo nvidia-ctk cdi generate --output=$CDI_PATH)"
fi

# ── #4 CDI spec drift after driver update ────────────────────────────────
print_header "#4 CDI spec freshness vs. driver"
if [ -f "$CDI_PATH" ]; then
  CDI_EPOCH="$(stat -c '%Y' "$CDI_PATH" 2>/dev/null || echo 0)"
  # Heuristic: locate any nvidia.ko* under /lib/modules or /usr/lib/modules; take newest mtime.
  DRIVER_NEWEST_EPOCH=0
  while IFS= read -r f; do
    mt="$(stat -c '%Y' "$f" 2>/dev/null || echo 0)"
    if [ "$mt" -gt "$DRIVER_NEWEST_EPOCH" ]; then
      DRIVER_NEWEST_EPOCH="$mt"
    fi
  done < <(find /lib/modules /usr/lib/modules -maxdepth 6 -name 'nvidia*.ko*' 2>/dev/null)
  if [ "$DRIVER_NEWEST_EPOCH" -eq 0 ]; then
    print_check 4 "CDI spec vs driver mtime" INFO "driver module path not located on this distro — skipped"
  elif [ "$CDI_EPOCH" -lt "$DRIVER_NEWEST_EPOCH" ]; then
    print_check 4 "CDI spec vs driver mtime" WARN "CDI spec is older than driver modules — regenerate with: sudo nvidia-ctk cdi generate --output=$CDI_PATH"
  else
    print_check 4 "CDI spec vs driver mtime" PASS "spec newer or equal to driver modules"
  fi
else
  print_check 4 "CDI spec vs driver mtime" INFO "skipped — no CDI spec to compare"
fi

# ── #5 /dev/char NVIDIA symlinks ─────────────────────────────────────────
print_header "#5 /dev/char NVIDIA symlinks"
if [ -d /dev/char ]; then
  CHAR_NV_COUNT="$(ls -1 /dev/char 2>/dev/null | grep -c '^195:' || true)"
  if [ "$CHAR_NV_COUNT" -gt 0 ]; then
    print_check 5 "/dev/char NVIDIA symlinks" PASS "found $CHAR_NV_COUNT entries with major 195"
  else
    print_check 5 "/dev/char NVIDIA symlinks" FAIL "missing — fix: sudo nvidia-ctk system create-dev-char-symlinks --create-all (also add udev rule per nvidia-container-toolkit issue #48)"
  fi
else
  print_check 5 "/dev/char NVIDIA symlinks" WARN "/dev/char does not exist on this host"
fi

# ── #6 NVIDIA kernel modules ─────────────────────────────────────────────
print_header "#6 NVIDIA kernel modules"
LSMOD_OUTPUT="$(lsmod 2>/dev/null | awk '{print $1}' || true)"
for mod in nvidia nvidia_modeset nvidia_uvm nvidia_drm; do
  if echo "$LSMOD_OUTPUT" | grep -qx "$mod"; then
    print_check 6 "module $mod loaded" PASS ""
  else
    if [ "$mod" = "nvidia_uvm" ]; then
      print_check 6 "module $mod loaded" FAIL "fix: sudo modprobe $mod (or sudo rmmod $mod && sudo modprobe $mod after suspend/resume)"
    else
      print_check 6 "module $mod loaded" WARN "fix: sudo modprobe $mod"
    fi
  fi
done

# ── #7 Docker daemon config ──────────────────────────────────────────────
print_header "#7 Docker daemon config"
DAEMON_JSON="/etc/docker/daemon.json"
if [ -r "$DAEMON_JSON" ]; then
  echo "--- $DAEMON_JSON ---"
  cat "$DAEMON_JSON"
  echo "--------------------"
  if grep -q 'native.cgroupdriver=systemd' "$DAEMON_JSON" 2>/dev/null; then
    print_check 7 "Docker cgroup driver" WARN "uses systemd cgroups — NVIDIA recommends cgroupfs for GPU workloads (set exec-opts native.cgroupdriver=cgroupfs and restart docker)"
  else
    print_check 7 "Docker cgroup driver" PASS "no systemd cgroupdriver override detected in daemon.json"
  fi
else
  print_check 7 "Docker daemon.json" INFO "no daemon.json present (Docker uses defaults)"
fi
NCT_CONFIG="/etc/nvidia-container-runtime/config.toml"
if [ -r "$NCT_CONFIG" ]; then
  echo "--- $NCT_CONFIG ---"
  grep -E 'no-cgroups|^\[' "$NCT_CONFIG" || true
  echo "-------------------"
fi

# ── #8 Docker runtime info ───────────────────────────────────────────────
print_header "#8 Docker runtime info"
if command -v docker >/dev/null 2>&1; then
  DOCKER_INFO="$(docker info --format '{{json .}}' 2>/dev/null || echo '{}')"
  echo "Runtimes: $(echo "$DOCKER_INFO" | grep -oP '"Runtimes":\{[^}]*\}' || echo 'unparseable')"
  echo "DefaultRuntime: $(echo "$DOCKER_INFO" | grep -oP '"DefaultRuntime":"[^"]*"' || echo 'unknown')"
  echo "CgroupDriver: $(echo "$DOCKER_INFO" | grep -oP '"CgroupDriver":"[^"]*"' || echo 'unknown')"
  print_check 8 "docker info readable" PASS ""
else
  print_check 8 "docker present" FAIL "docker CLI not in PATH"
fi

# ── #9 Smoke test: --gpus all in a small NVIDIA base image ──────────────
print_header "#9 Container smoke test"
SMOKE_IMAGE="nvidia/cuda:12.6.0-base-ubuntu24.04"
if ! command -v docker >/dev/null 2>&1; then
  print_check 9 "container --gpus all smoke test" INFO "skipped — docker not present"
elif ! docker image inspect "$SMOKE_IMAGE" >/dev/null 2>&1; then
  echo "Image $SMOKE_IMAGE not present locally; this check would pull ~150MB."
  echo "Skipping the pull. To run manually: docker pull $SMOKE_IMAGE"
  print_check 9 "container --gpus all smoke test" INFO "skipped — image not pulled (would pull ~150MB)"
else
  echo "Running: docker run --rm --gpus all $SMOKE_IMAGE nvidia-smi"
  if SMOKE_OUT="$(docker run --rm --gpus all "$SMOKE_IMAGE" nvidia-smi 2>&1)"; then
    echo "$SMOKE_OUT" | head -n 20
    print_check 9 "container --gpus all smoke test" PASS "GPU visible inside a fresh NVIDIA base container"
  else
    echo "$SMOKE_OUT"
    print_check 9 "container --gpus all smoke test" FAIL "GPU NOT visible inside container — host-side breakage confirmed; see checks #5/#6/#3 for the most likely fix"
  fi
fi

# ── #10 NVIDIA proc files inside a container (only if smoke passed) ─────
print_header "#10 NVIDIA proc files inside container"
if docker image inspect "$SMOKE_IMAGE" >/dev/null 2>&1; then
  if PROC_OUT="$(docker run --rm --gpus all "$SMOKE_IMAGE" bash -c 'ls /dev/nvidia* 2>&1; echo ---; cat /proc/driver/nvidia/version 2>&1' 2>&1)"; then
    echo "$PROC_OUT"
    print_check 10 "container can read /dev/nvidia* and /proc/driver/nvidia" PASS ""
  else
    echo "$PROC_OUT"
    print_check 10 "container can read /dev/nvidia* and /proc/driver/nvidia" FAIL "container has --gpus all but cannot read NVIDIA proc files"
  fi
else
  print_check 10 "container can read NVIDIA proc files" INFO "skipped — image not pulled"
fi

# ── #11 Summary ─────────────────────────────────────────────────────────
print_header "#11 Summary"
echo "PASS: $PASS_COUNT   WARN: $WARN_COUNT   FAIL: $FAIL_COUNT"
echo
if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "RESULT: One or more FAIL checks. See scripts/README-gpu-diagnostic.md"
  echo "        for the recommended fix per failure mode."
elif [ "$WARN_COUNT" -gt 0 ]; then
  echo "RESULT: Some WARN checks — host is likely operational but not optimally"
  echo "        configured. Review WARN entries above."
else
  echo "RESULT: All checks PASS — host GPU/Docker setup looks healthy."
fi
echo
echo "Full log: $LOGFILE"
exit 0
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x scripts/diagnose-gpu.sh
```

- [ ] **Step 3: Run it on this machine to confirm it works**

```bash
bash scripts/diagnose-gpu.sh > /tmp/gpu-diag-test.log 2>&1
echo "Exit code: $?"
ls -la gpu-diagnostic-*.log | head -1
grep -E '^\[(PASS|WARN|FAIL|INFO)\]' /tmp/gpu-diag-test.log | head -20
```

Expected: exit code 0; a `gpu-diagnostic-<timestamp>.log` file is created in the current directory; at least the "#1 nvidia-smi present" line appears with one of PASS/FAIL.

- [ ] **Step 4: Commit**

```bash
git add scripts/diagnose-gpu.sh
git commit -m "feat(scripts): add observation-only GPU diagnostic for CUDA error 999

* feat(scripts): scripts/diagnose-gpu.sh — 11 read-only host checks (driver, nvidia-container-toolkit, CDI spec age, /dev/char symlinks, NVIDIA kernel modules, Docker daemon config, container smoke test) with PASS/WARN/FAIL summary; tees output to gpu-diagnostic-<UTC>.log; exits cleanly on non-Linux"
```

---

## Task 2: Create companion README

**Files:**
- Create: `scripts/README-gpu-diagnostic.md`

- [ ] **Step 1: Write the README**

Create `scripts/README-gpu-diagnostic.md`:

```markdown
# `diagnose-gpu.sh` — GPU host diagnostic

Runs 11 read-only checks against a Linux NVIDIA host to identify why a Docker
container can fail to initialise CUDA (PyTorch error 999, "CUDA unknown error")
even when `nvidia-smi` succeeds on the host.

The script is **observation-only**: no `sudo`, no package operations, no
mutations to your system. Output is tee'd to both stdout and a timestamped
`gpu-diagnostic-<UTC>.log` file in the current directory so it can be pasted
back without loss.

## When to run it

- The TranscriptionSuite server logs `CUDA health check failed — GPU
  transcription disabled for this session`.
- The dashboard's GPU Health card shows yellow or red.
- A fresh container start hangs at GPU init or falls back to CPU
  unexpectedly.
- After any `pacman -Syu` / `apt upgrade` / `dnf upgrade` that bumped
  `nvidia-utils`, `nvidia-dkms`, `nvidia-container-toolkit`, or the kernel.

## Usage

```
bash scripts/diagnose-gpu.sh
```

The script exits 0 on every platform — on macOS / Windows it prints a friendly
"Linux only" message and returns. On Linux it always completes the 11 checks
even if some fail.

## What each check measures and how to fix it

| # | Check | What it measures | If it fails |
|---|---|---|---|
| 1 | `nvidia-smi present` | NVIDIA userspace driver tool is installed | Install the NVIDIA driver from your distro (e.g. `sudo pacman -S nvidia` on Arch). |
| 2 | `nvidia-ctk installed` | NVIDIA Container Toolkit is installed | `sudo pacman -S nvidia-container-toolkit` (or distro equivalent). Required for both CDI and legacy modes. |
| 3 | `CDI spec at /etc/cdi/nvidia.yaml` | The CDI spec file exists | Only matters if the dashboard auto-detected CDI mode. Generate with `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`. |
| 4 | `CDI spec vs driver mtime` | The CDI spec is newer than the installed driver | The spec is a static snapshot. Regenerate after any driver update: `sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`. |
| 5 | `/dev/char NVIDIA symlinks` | Symlinks under `/dev/char/195:*` exist for the NVIDIA char devices | This is the most common Phase-1 root cause. Run `sudo nvidia-ctk system create-dev-char-symlinks --create-all`. To make it persistent across reboots, install the udev rule from [NVIDIA/nvidia-container-toolkit issue #48](https://github.com/NVIDIA/nvidia-container-toolkit/issues/48). |
| 6 | NVIDIA kernel modules loaded | `nvidia`, `nvidia_modeset`, `nvidia_uvm`, `nvidia_drm` are loaded | `sudo modprobe nvidia_uvm` (replace with the missing module). After suspend/resume you may need `sudo rmmod nvidia_uvm && sudo modprobe nvidia_uvm`. If `modprobe` fails, your DKMS module did not rebuild for the running kernel — reboot, or rebuild via `sudo dkms autoinstall`. |
| 7 | Docker daemon config | `/etc/docker/daemon.json` does not force the systemd cgroup driver | Add `"exec-opts": ["native.cgroupdriver=cgroupfs"]` to `/etc/docker/daemon.json`, then `sudo systemctl restart docker`. NVIDIA documents this for GPU workloads. |
| 8 | `docker info` | Docker is reachable and reports its runtimes / cgroup driver | Confirm Docker is running: `sudo systemctl status docker`. |
| 9 | Container smoke test | `docker run --rm --gpus all <NVIDIA base image> nvidia-smi` succeeds | If checks 5/6/3 are clean and this still fails, capture the exact docker error — it usually names the missing piece (`failed to inject CDI devices`, `unknown runtime: nvidia`, etc.). |
| 10 | NVIDIA proc files inside container | `/dev/nvidia*` and `/proc/driver/nvidia/version` are readable inside the container | Same fixes as check 9. |
| 11 | Summary | PASS / WARN / FAIL totals | — |

## References

- [NVIDIA Container Toolkit Troubleshooting](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/troubleshooting.html)
- [NVIDIA/nvidia-container-toolkit Issue #48](https://github.com/NVIDIA/nvidia-container-toolkit/issues/48)
- [Arch Linux forum — Docker with GPU NVML Unknown Error](https://bbs.archlinux.org/viewtopic.php?id=266915)
- [PyTorch issue #115340](https://github.com/pytorch/pytorch/issues/115340)
- Internal spec: `docs/superpowers/specs/2026-04-29-cuda-error-999-recovery-design.md`
```

- [ ] **Step 2: Commit**

```bash
git add scripts/README-gpu-diagnostic.md
git commit -m "docs(scripts): add README for diagnose-gpu.sh

* docs(scripts): scripts/README-gpu-diagnostic.md — explain when to run the diagnostic, what each of the 11 checks measures, and the canonical NVIDIA-doc fix command for each failure mode"
```

---

# Phase 2 — Backend `recovery_hint`

## Task 3: TDD — write failing tests for `recovery_hint`

**Files:**
- Modify: `server/backend/tests/test_audio_utils.py`

- [ ] **Step 1: Add the test class to the bottom of `TestCudaHealthCheck` block**

Open `server/backend/tests/test_audio_utils.py` and add the following to the existing `TestCudaHealthCheck` class (after `test_retry_also_fails_returns_no_cuda` at ~line 221):

```python
    def test_error_999_unrecoverable_includes_recovery_hint(self):
        """When error 999 fails all retries, result includes a recovery_hint."""
        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = RuntimeError("CUDA unknown error")

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "_capture_nvidia_smi", return_value="ok"),
            patch.object(au, "time"),
        ):
            result = au.cuda_health_check()

        assert result["status"] == "unrecoverable"
        hint = result.get("recovery_hint")
        assert hint is not None
        assert "error 999" in hint.lower() or "cuda unknown" in hint.lower()
        assert "diagnose-gpu.sh" in hint

    def test_error_999_recovered_omits_recovery_hint(self):
        """If error 999 recovers on retry, no recovery_hint is added."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA RTX 3060"
        mock_props.total_mem = 12 * 1024**3

        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = [RuntimeError("CUDA unknown error"), None]
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with (
            patch.object(au, "torch", mock_torch),
            patch.object(au, "HAS_TORCH", True),
            patch.object(au, "time"),
        ):
            result = au.cuda_health_check()

        assert result["status"] == "healthy"
        assert "recovery_hint" not in result

    def test_non_999_unrecoverable_omits_recovery_hint(self):
        """A non-999 error path that still yields a non-healthy status must not
        carry the error-999-specific recovery_hint."""
        mock_torch = MagicMock()
        mock_torch.cuda.init.side_effect = RuntimeError("no CUDA-capable device")

        with patch.object(au, "torch", mock_torch), patch.object(au, "HAS_TORCH", True):
            result = au.cuda_health_check()

        assert result["status"] == "no_cuda"
        assert "recovery_hint" not in result
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_audio_utils.py::TestCudaHealthCheck::test_error_999_unrecoverable_includes_recovery_hint tests/test_audio_utils.py::TestCudaHealthCheck::test_error_999_recovered_omits_recovery_hint tests/test_audio_utils.py::TestCudaHealthCheck::test_non_999_unrecoverable_omits_recovery_hint -v
```

Expected: 1 FAILED (the unrecoverable case — no `recovery_hint` key yet) and 2 PASSED (the cases where the key should be absent are already absent).

---

## Task 4: Implement `recovery_hint` in `cuda_health_check`

**Files:**
- Modify: `server/backend/core/audio_utils.py:251-265`

- [ ] **Step 1: Update the unrecoverable branch to attach the hint**

Open `server/backend/core/audio_utils.py`. Locate the unrecoverable branch inside `cuda_health_check` (around line 251):

```python
            # All retries exhausted — mark as unrecoverable.
            _cuda_probe_failed = True
            smi_output = _capture_nvidia_smi()
            logger.error(
                "CUDA health check: unrecoverable GPU state after %d retries",
                len(_error_999_delays),
                exc_info=last_exc,
                extra={"nvidia_smi": smi_output},
            )
            return {
                "status": "unrecoverable",
                "error": str(last_exc),
                "nvidia_smi": smi_output,
                "attempts": len(_error_999_delays) + 1,
            }
```

Replace it with:

```python
            # All retries exhausted — mark as unrecoverable.
            _cuda_probe_failed = True
            smi_output = _capture_nvidia_smi()
            recovery_hint = (
                "GPU init failed with error 999 (CUDA unknown). This is "
                "almost always host-side: missing /dev/char symlinks, stale "
                "CDI spec, nvidia_uvm not loaded, or systemd cgroup driver "
                "interference. Run scripts/diagnose-gpu.sh on the host for "
                "details and the recommended fix."
            )
            logger.error(
                "CUDA health check: unrecoverable GPU state after %d retries",
                len(_error_999_delays),
                exc_info=last_exc,
                extra={"nvidia_smi": smi_output, "recovery_hint": recovery_hint},
            )
            return {
                "status": "unrecoverable",
                "error": str(last_exc),
                "nvidia_smi": smi_output,
                "attempts": len(_error_999_delays) + 1,
                "recovery_hint": recovery_hint,
            }
```

- [ ] **Step 2: Run the three new tests — they should now pass**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_audio_utils.py::TestCudaHealthCheck -v
```

Expected: all `TestCudaHealthCheck` tests pass (including the three new `recovery_hint` tests).

- [ ] **Step 3: Run the full audio_utils test file to confirm no regressions**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/test_audio_utils.py -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add server/backend/core/audio_utils.py server/backend/tests/test_audio_utils.py
git commit -m "feat(server, audio_utils): add recovery_hint field for error-999 unrecoverable GPU state

* feat(server, audio_utils): cuda_health_check() now returns recovery_hint field on the unrecoverable branch, pointing the user at scripts/diagnose-gpu.sh and naming the four likely host-side causes (/dev/char symlinks, stale CDI spec, nvidia_uvm not loaded, systemd cgroup driver). The hint is omitted on healthy/recovered/no_cuda paths so consumers can branch on its presence.

* test(server, audio_utils): three new TestCudaHealthCheck cases — hint present on error-999 unrecoverable, hint absent on error-999 recovered, hint absent on non-999 errors"
```

---

## Task 5: Surface `recovery_hint` in lifespan log

**Files:**
- Modify: `server/backend/api/main.py:511-519`

- [ ] **Step 1: Update the lifespan error log to include the hint**

Open `server/backend/api/main.py`. Locate the unrecoverable branch (around line 511):

```python
    if gpu_unrecoverable:
        logger.error(
            "CUDA health check failed — GPU transcription disabled for this session",
            extra={
                "error": gpu_health["error"],
                "nvidia_smi": gpu_health.get("nvidia_smi", "N/A"),
            },
        )
        app.state.gpu_error = gpu_health
```

Replace with:

```python
    if gpu_unrecoverable:
        logger.error(
            "CUDA health check failed — GPU transcription disabled for this session",
            extra={
                "error": gpu_health["error"],
                "nvidia_smi": gpu_health.get("nvidia_smi", "N/A"),
                "recovery_hint": gpu_health.get("recovery_hint"),
            },
        )
        app.state.gpu_error = gpu_health
```

(`app.state.gpu_error = gpu_health` already carries the new `recovery_hint` field through to any HTTP route that reads `app.state.gpu_error`, because the dict reference is shared.)

- [ ] **Step 2: Verify the import and usage compile cleanly**

```bash
cd server/backend
../../build/.venv/bin/python -c "import ast; ast.parse(open('api/main.py').read()); print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add server/backend/api/main.py
git commit -m "feat(server, lifespan): include recovery_hint in unrecoverable-GPU error log

* feat(server, lifespan): the structured logger now emits the recovery_hint alongside the existing error/nvidia_smi fields when cuda_health_check returns unrecoverable, so log readers see the diagnostic-script pointer immediately"
```

---

# Phase 2 — Dashboard preflight

## Task 6: TDD — write failing tests for `validateGpuPreflight`

**Files:**
- Create: `dashboard/electron/__tests__/dockerManagerGpuPreflight.test.ts`

- [ ] **Step 1: Create the test file**

Create `dashboard/electron/__tests__/dockerManagerGpuPreflight.test.ts`:

```typescript
// @vitest-environment node

/**
 * GPU preflight — validates the cheap subset of scripts/diagnose-gpu.sh that
 * runs at dashboard startup. Mirrors the dockerManagerVulkanPreflight test
 * pattern: the function under test is pure (all OS access is injected) and
 * returns a structured result the UI renders.
 */

import { describe, it, expect, vi } from 'vitest';

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getPath: (name: string) => `/tmp/mock-${name}`,
    setPath: vi.fn(),
  },
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    get() {
      return undefined;
    }
    set() {}
  },
}));

import { validateGpuPreflight } from '../dockerManager.js';

interface Env {
  cdiExists: boolean;
  cdiMtime: number;
  driverMtime: number;
  charSymlinks: string[];
  lsmodOutput: string;
}

function makeDeps(env: Env) {
  return {
    fsExists: (p: string) => {
      if (p === '/etc/cdi/nvidia.yaml') return env.cdiExists;
      if (p === '/dev/char') return true;
      return false;
    },
    readDir: (p: string) => {
      if (p === '/dev/char') return env.charSymlinks;
      return [];
    },
    statMtime: (p: string) => {
      if (p === '/etc/cdi/nvidia.yaml') return env.cdiExists ? env.cdiMtime : null;
      if (p.includes('/lib/modules')) return env.driverMtime;
      return null;
    },
    runLsmod: () => env.lsmodOutput,
  };
}

const healthyEnv: Env = {
  cdiExists: true,
  cdiMtime: 2_000_000_000,
  driverMtime: 1_000_000_000,
  charSymlinks: ['195:0', '195:255', '512:0'],
  lsmodOutput: 'nvidia\nnvidia_modeset\nnvidia_uvm\nnvidia_drm\n',
};

describe('validateGpuPreflight', () => {
  it('non-Linux platform: returns status=unknown, no checks run', () => {
    const deps = makeDeps(healthyEnv);
    const result = validateGpuPreflight('darwin', deps);
    expect(result.status).toBe('unknown');
    expect(result.checks).toEqual([]);
  });

  it('Windows: returns status=unknown, no checks run', () => {
    const deps = makeDeps(healthyEnv);
    const result = validateGpuPreflight('win32', deps);
    expect(result.status).toBe('unknown');
    expect(result.checks).toEqual([]);
  });

  it('Linux + healthy environment: status=healthy, all checks pass', () => {
    const result = validateGpuPreflight('linux', makeDeps(healthyEnv));
    expect(result.status).toBe('healthy');
    expect(result.checks.every((c) => c.pass)).toBe(true);
    expect(result.checks.map((c) => c.name)).toEqual([
      'CDI spec exists',
      'CDI spec newer than driver',
      '/dev/char NVIDIA symlinks',
      'nvidia_uvm module loaded',
    ]);
  });

  it('Linux + missing /dev/char symlinks: status=warning, fixCommand provided', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, charSymlinks: ['512:0', '999:1'] }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === '/dev/char NVIDIA symlinks');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk system create-dev-char-symlinks/);
  });

  it('Linux + stale CDI spec: status=warning with regenerate command', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, cdiMtime: 500_000_000, driverMtime: 1_000_000_000 }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk cdi generate/);
  });

  it('Linux + missing CDI spec: status=warning, generate command shown', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, cdiExists: false }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === 'CDI spec exists');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/nvidia-ctk cdi generate/);
    // The "newer than driver" check is skipped (passes vacuously) when the spec is missing.
    const driverCheck = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(driverCheck?.pass).toBe(true);
  });

  it('Linux + nvidia_uvm not loaded: status=warning, modprobe command shown', () => {
    const result = validateGpuPreflight(
      'linux',
      makeDeps({ ...healthyEnv, lsmodOutput: 'nvidia\nnvidia_modeset\nnvidia_drm\n' }),
    );
    expect(result.status).toBe('warning');
    const failed = result.checks.find((c) => c.name === 'nvidia_uvm module loaded');
    expect(failed?.pass).toBe(false);
    expect(failed?.fixCommand).toMatch(/modprobe nvidia_uvm/);
  });

  it('Linux + missing driver mtime info: skips comparison, no warning', () => {
    const deps = {
      ...makeDeps(healthyEnv),
      statMtime: (p: string) => {
        if (p === '/etc/cdi/nvidia.yaml') return 2_000_000_000;
        return null; // driver path not located
      },
    };
    const result = validateGpuPreflight('linux', deps);
    const driverCheck = result.checks.find((c) => c.name === 'CDI spec newer than driver');
    expect(driverCheck?.pass).toBe(true); // conservative: skip rather than false-warn
  });
});
```

- [ ] **Step 2: Run the new test file — it should fail with import error**

```bash
cd dashboard
npx vitest run electron/__tests__/dockerManagerGpuPreflight.test.ts
```

Expected: FAIL with `validateGpuPreflight is not exported from '../dockerManager.js'` (or similar).

---

## Task 7: Implement `validateGpuPreflight`

**Files:**
- Modify: `dashboard/electron/dockerManager.ts` — add type and function near the existing `checkVulkanSupport` definition (line 130) for code locality.

- [ ] **Step 1: Add the type and pure function to `dockerManager.ts`**

Open `dashboard/electron/dockerManager.ts`. Add the following block immediately after the existing `checkVulkanSupport` function (around line 220 — find the closing `}` of `checkVulkanSupport` and insert after it):

```typescript
// ─── GPU Preflight (NVIDIA, Linux) ─────────────────────────────────────────
// Runs the cheap subset of scripts/diagnose-gpu.sh at dashboard startup so
// the GpuHealthCard can warn about misconfigurations before the container
// is started. Pure function — all OS access is injected for testability.

export interface GpuPreflightCheck {
  name: string;
  pass: boolean;
  /** Documented NVIDIA fix command. Present only when pass=false. */
  fixCommand?: string;
  /** External URL with more context. Present only when pass=false. */
  docsUrl?: string;
}

export interface GpuPreflightResult {
  status: 'healthy' | 'warning' | 'unknown';
  checks: GpuPreflightCheck[];
}

export interface GpuPreflightDeps {
  fsExists: (path: string) => boolean;
  readDir: (path: string) => string[];
  /** Returns mtime (epoch seconds) or null when the path cannot be stat'd. */
  statMtime: (path: string) => number | null;
  /** Returns lsmod stdout (one module name per line). Empty string on failure. */
  runLsmod: () => string;
}

const NVIDIA_DRIVER_MTIME_PATHS: readonly string[] = [
  '/lib/modules',
  '/usr/lib/modules',
];
const CDI_SPEC_PATH = '/etc/cdi/nvidia.yaml';

function newestDriverMtime(statMtime: GpuPreflightDeps['statMtime']): number | null {
  // Conservative heuristic: try a handful of distro-typical roots. The actual
  // recursive walk lives in the IPC handler — we just take what it produces.
  let newest: number | null = null;
  for (const root of NVIDIA_DRIVER_MTIME_PATHS) {
    const mt = statMtime(root);
    if (mt !== null && (newest === null || mt > newest)) {
      newest = mt;
    }
  }
  return newest;
}

export function validateGpuPreflight(
  platform: NodeJS.Platform,
  deps: GpuPreflightDeps,
): GpuPreflightResult {
  if (platform !== 'linux') {
    return { status: 'unknown', checks: [] };
  }

  const checks: GpuPreflightCheck[] = [];

  // Check 1: CDI spec exists
  const cdiExists = deps.fsExists(CDI_SPEC_PATH);
  checks.push({
    name: 'CDI spec exists',
    pass: cdiExists,
    fixCommand: cdiExists
      ? undefined
      : `sudo nvidia-ctk cdi generate --output=${CDI_SPEC_PATH}`,
    docsUrl: cdiExists
      ? undefined
      : 'https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html',
  });

  // Check 2: CDI spec newer than driver (only meaningful when both mtimes available)
  const cdiMtime = cdiExists ? deps.statMtime(CDI_SPEC_PATH) : null;
  const driverMtime = newestDriverMtime(deps.statMtime);
  let cdiFresh = true;
  if (cdiMtime !== null && driverMtime !== null && cdiMtime < driverMtime) {
    cdiFresh = false;
  }
  checks.push({
    name: 'CDI spec newer than driver',
    pass: cdiFresh,
    fixCommand: cdiFresh
      ? undefined
      : `sudo nvidia-ctk cdi generate --output=${CDI_SPEC_PATH}`,
  });

  // Check 3: /dev/char symlinks for major 195 (NVIDIA)
  const charEntries = deps.fsExists('/dev/char') ? deps.readDir('/dev/char') : [];
  const hasNvidiaSymlinks = charEntries.some((e) => e.startsWith('195:'));
  checks.push({
    name: '/dev/char NVIDIA symlinks',
    pass: hasNvidiaSymlinks,
    fixCommand: hasNvidiaSymlinks
      ? undefined
      : 'sudo nvidia-ctk system create-dev-char-symlinks --create-all',
    docsUrl: hasNvidiaSymlinks
      ? undefined
      : 'https://github.com/NVIDIA/nvidia-container-toolkit/issues/48',
  });

  // Check 4: nvidia_uvm kernel module loaded
  const lsmodLines = deps.runLsmod().split('\n').map((l) => l.trim());
  const uvmLoaded = lsmodLines.includes('nvidia_uvm');
  checks.push({
    name: 'nvidia_uvm module loaded',
    pass: uvmLoaded,
    fixCommand: uvmLoaded ? undefined : 'sudo modprobe nvidia_uvm',
  });

  const status: GpuPreflightResult['status'] = checks.every((c) => c.pass)
    ? 'healthy'
    : 'warning';

  return { status, checks };
}
```

- [ ] **Step 2: Run the test file — it should now pass**

```bash
cd dashboard
npx vitest run electron/__tests__/dockerManagerGpuPreflight.test.ts
```

Expected: all 8 tests pass.

- [ ] **Step 3: Run the full electron test suite to confirm no regressions**

```bash
cd dashboard
npx vitest run electron/
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add dashboard/electron/dockerManager.ts dashboard/electron/__tests__/dockerManagerGpuPreflight.test.ts
git commit -m "feat(dashboard, electron): add validateGpuPreflight pure function for NVIDIA host checks

* feat(dashboard, electron): dockerManager.ts now exports GpuPreflightCheck/Result/Deps types and a pure validateGpuPreflight(platform, deps) function that runs the cheap subset of scripts/diagnose-gpu.sh — CDI spec presence, CDI spec freshness vs driver, /dev/char NVIDIA symlinks, nvidia_uvm module load. Each failing check carries the documented NVIDIA fix command and docs URL. Returns status=unknown on non-Linux without touching the filesystem.

* test(dashboard, electron): dockerManagerGpuPreflight.test.ts mirrors the existing checkVulkanSupport test layout — non-Linux gating, healthy environment, each individual check failure mode, and the conservative skip when driver mtime cannot be located"
```

---

## Task 8: Wire `validateGpuPreflight` to IPC

**Files:**
- Modify: `dashboard/electron/dockerManager.ts` — add a non-pure wrapper that fills in real `fs`/shell deps.
- Modify: `dashboard/electron/main.ts` — add `docker:validateGpuPreflight` IPC handler.
- Modify: `dashboard/electron/preload.ts` — expose `docker.validateGpuPreflight()` plus its type.

- [ ] **Step 1: Add a real-deps wrapper to `dockerManager.ts`**

First ensure `execSync` is importable. At the top of `dockerManager.ts`, near other Node/Electron imports, add (if not already present):

```typescript
import { execSync } from 'child_process';
```

(Search the file first: `grep -n "from 'child_process'" dashboard/electron/dockerManager.ts` — extend the existing import list if `child_process` is already imported.)

Then add this immediately after `validateGpuPreflight` in `dockerManager.ts`:

```typescript
/**
 * Real-OS wrapper around validateGpuPreflight() — used by the
 * docker:validateGpuPreflight IPC handler. Kept separate from the pure
 * function so tests can inject without touching fs/exec.
 */
export function runGpuPreflight(): GpuPreflightResult {
  // Lazy-import fs so the unit tests can mock electron without dragging in
  // real fs operations during validateGpuPreflight() unit tests.
  // (validateGpuPreflight() itself is pure; this wrapper is the impure shell.)
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('fs') as typeof import('fs');

  const deps: GpuPreflightDeps = {
    fsExists: (p) => {
      try {
        return fs.existsSync(p);
      } catch {
        return false;
      }
    },
    readDir: (p) => {
      try {
        return fs.readdirSync(p);
      } catch {
        return [];
      }
    },
    statMtime: (p) => {
      try {
        // For directory roots we want the latest modification time of any
        // file underneath — but a deep walk is too expensive at preflight.
        // Stat the root itself; that's enough to compare with the CDI spec
        // mtime (driver updates touch the modules root directory).
        return Math.floor(fs.statSync(p).mtimeMs / 1000);
      } catch {
        return null;
      }
    },
    runLsmod: () => {
      try {
        return execSync('lsmod', { timeout: 2000, encoding: 'utf8' });
      } catch {
        return '';
      }
    },
  };

  return validateGpuPreflight(process.platform, deps);
}
```

- [ ] **Step 2: Add the IPC handler in `main.ts`**

Open `dashboard/electron/main.ts`. After the existing `ipcMain.handle('docker:checkGpu', ...)` block (around line 1163), add:

```typescript
ipcMain.handle('docker:validateGpuPreflight', async () => {
  return dockerManager.runGpuPreflight();
});
```

- [ ] **Step 3: Expose the API in `preload.ts`**

Open `dashboard/electron/preload.ts`. In the `docker:` interface block (around line 137), add the type after `checkGpu`:

```typescript
    checkGpu: () => Promise<{ gpu: boolean; toolkit: boolean; vulkan: boolean }>;
    validateGpuPreflight: () => Promise<{
      status: 'healthy' | 'warning' | 'unknown';
      checks: Array<{
        name: string;
        pass: boolean;
        fixCommand?: string;
        docsUrl?: string;
      }>;
    }>;
```

Then in the implementation block (around line 475 where `checkGpu` is wired), add:

```typescript
    checkGpu: () => ipcRenderer.invoke('docker:checkGpu'),
    validateGpuPreflight: () => ipcRenderer.invoke('docker:validateGpuPreflight'),
```

- [ ] **Step 4: Verify the dashboard still type-checks**

```bash
cd dashboard
npx tsc --noEmit -p electron/tsconfig.json
```

Expected: no errors.

- [ ] **Step 5: Run the full electron test suite**

```bash
cd dashboard
npx vitest run electron/
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add dashboard/electron/dockerManager.ts dashboard/electron/main.ts dashboard/electron/preload.ts
git commit -m "feat(dashboard, electron): expose validateGpuPreflight over docker IPC

* feat(dashboard, electron): dockerManager.ts now exports a runGpuPreflight() wrapper that fills the pure validateGpuPreflight() with real fs.existsSync/readdirSync/statSync and execSync('lsmod') — kept separate so unit tests can keep injecting mock dependencies

* feat(dashboard, electron): main.ts adds the docker:validateGpuPreflight IPC handler; preload.ts exposes window.electronAPI.docker.validateGpuPreflight() with the matching type"
```

---

# Phase 2 — Run Full Diagnostic IPC

## Task 9: Bundle the diagnostic script with the packaged app

**Files:**
- Modify: `dashboard/package.json:89-130` — add `scripts/diagnose-gpu.sh` to `extraResources`.

- [ ] **Step 1: Append the script to the existing extraResources array**

Open `dashboard/package.json`. Locate the `extraResources` array (line ~89). Inside the array, **after the last existing object and before the closing `]`**, add:

```json
      ,
      {
        "from": "../scripts/diagnose-gpu.sh",
        "to": "scripts/diagnose-gpu.sh"
      },
      {
        "from": "../scripts/README-gpu-diagnostic.md",
        "to": "scripts/README-gpu-diagnostic.md"
      }
```

(If the existing last entry already has a trailing comma after it, do not add another one — adapt to whatever JSON style the file already uses.)

- [ ] **Step 2: Verify package.json is still valid JSON**

```bash
cd dashboard
node -e "JSON.parse(require('fs').readFileSync('package.json','utf8')); console.log('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add dashboard/package.json
git commit -m "chore(dashboard, build): bundle scripts/diagnose-gpu.sh and README into packaged app

* chore(dashboard, build): package.json extraResources now copies scripts/diagnose-gpu.sh and scripts/README-gpu-diagnostic.md into the packaged Electron app under resources/scripts/, so the GpuHealthCard 'Run Full Diagnostic' button can locate the script in both dev (../scripts/) and production (process.resourcesPath/scripts/) builds"
```

---

## Task 10: Add `docker:runGpuDiagnostic` IPC handler

**Files:**
- Modify: `dashboard/electron/dockerManager.ts` — add `runGpuDiagnostic()` that spawns the script.
- Modify: `dashboard/electron/main.ts` — add the IPC handler.
- Modify: `dashboard/electron/preload.ts` — expose the renderer-side API.

- [ ] **Step 1: Add `runGpuDiagnostic` to `dockerManager.ts`**

Ensure these imports exist at the top of `dockerManager.ts` (extend the existing import lines for `child_process` and `electron`; add fresh imports for `path` and `os` if missing):

```typescript
import { execSync, spawn } from 'child_process';
import { app as electronApp } from 'electron';
import * as path from 'path';
import * as os from 'os';
```

(Search the file: `grep -n "^import" dashboard/electron/dockerManager.ts | head -20`. Merge with existing imports — do not create duplicates.)

Then add this after `runGpuPreflight` in `dockerManager.ts`:

```typescript
export interface RunGpuDiagnosticResult {
  status: 'started' | 'unsupported' | 'script-missing';
  /** Absolute path to the log file the script writes (when status=started). */
  logPath?: string;
  /** Resolved script path (always present for status=started or script-missing). */
  scriptPath?: string;
  /** The exact command string the user could run themselves. */
  manualCommand?: string;
}

function resolveDiagnosticScriptPath(): string {
  // Packaged: <app>/resources/scripts/diagnose-gpu.sh
  // Dev: <repo>/scripts/diagnose-gpu.sh (relative to dist-electron/dockerManager.js)
  if (electronApp.isPackaged) {
    return path.join(process.resourcesPath, 'scripts', 'diagnose-gpu.sh');
  }
  // __dirname at runtime is dist-electron/; the repo's scripts/ is two levels up.
  return path.resolve(__dirname, '..', '..', 'scripts', 'diagnose-gpu.sh');
}

export function runGpuDiagnostic(): RunGpuDiagnosticResult {
  if (process.platform !== 'linux') {
    return { status: 'unsupported' };
  }
  const scriptPath = resolveDiagnosticScriptPath();
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('fs') as typeof import('fs');
  if (!fs.existsSync(scriptPath)) {
    return {
      status: 'script-missing',
      scriptPath,
      manualCommand: `bash ${scriptPath}`,
    };
  }

  const ts = new Date().toISOString().replace(/[-:.]/g, '').slice(0, 15);
  const logPath = path.join(os.tmpdir(), `gpu-diagnostic-${ts}.log`);
  const out = fs.openSync(logPath, 'w');

  const child = spawn('bash', [scriptPath], {
    stdio: ['ignore', out, out],
    detached: true,
    cwd: os.tmpdir(),
  });
  child.unref();

  return {
    status: 'started',
    logPath,
    scriptPath,
    manualCommand: `bash ${scriptPath}`,
  };
}
```

- [ ] **Step 2: Add the IPC handler in `main.ts`**

In `dashboard/electron/main.ts`, after the `docker:validateGpuPreflight` handler from Task 8, add:

```typescript
ipcMain.handle('docker:runGpuDiagnostic', async () => {
  return dockerManager.runGpuDiagnostic();
});
```

- [ ] **Step 3: Expose the API in `preload.ts`**

In `dashboard/electron/preload.ts`, add the type after `validateGpuPreflight` in the `docker:` interface:

```typescript
    runGpuDiagnostic: () => Promise<{
      status: 'started' | 'unsupported' | 'script-missing';
      logPath?: string;
      scriptPath?: string;
      manualCommand?: string;
    }>;
```

And in the implementation block:

```typescript
    runGpuDiagnostic: () => ipcRenderer.invoke('docker:runGpuDiagnostic'),
```

- [ ] **Step 4: Verify type-checks**

```bash
cd dashboard
npx tsc --noEmit -p electron/tsconfig.json
```

Expected: no errors.

- [ ] **Step 5: Smoke test from the dev build**

```bash
cd dashboard
npm run dev:electron &
DEV_PID=$!
sleep 5
# Inspect the rendered UI by hand once integration is done in Task 12, or
# call the IPC handler from Electron devtools console:
#   await window.electronAPI.docker.runGpuDiagnostic();
# expected return: { status: 'started', logPath: '/tmp/gpu-diagnostic-…log', ... }
kill $DEV_PID 2>/dev/null || true
```

Expected: the IPC call returns `status: 'started'` and the `logPath` file exists in `/tmp`. (You can defer this manual smoke until after Task 12 wires up the button.)

- [ ] **Step 6: Commit**

```bash
git add dashboard/electron/dockerManager.ts dashboard/electron/main.ts dashboard/electron/preload.ts
git commit -m "feat(dashboard, electron): add runGpuDiagnostic IPC handler that spawns scripts/diagnose-gpu.sh

* feat(dashboard, electron): dockerManager.ts adds runGpuDiagnostic() that resolves the script path (packaged app: process.resourcesPath/scripts/; dev: ../../scripts/), spawns it detached with stdout/stderr redirected to /tmp/gpu-diagnostic-<ts>.log, and returns the log path so the UI can surface it

* feat(dashboard, electron): docker:runGpuDiagnostic IPC handler + window.electronAPI.docker.runGpuDiagnostic() preload binding. Returns 'unsupported' on non-Linux and 'script-missing' when the bundled script cannot be located, both with the manual command string for copy-paste"
```

---

# Phase 2 — `GpuHealthCard` component

## Task 11: TDD — write failing tests for `GpuHealthCard`

**Files:**
- Create: `dashboard/components/views/__tests__/GpuHealthCard.test.tsx`

- [ ] **Step 1: Create the test file**

```typescript
// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { GpuHealthCard } from '../GpuHealthCard';

const healthyPreflight = {
  status: 'healthy' as const,
  checks: [
    { name: 'CDI spec exists', pass: true },
    { name: 'CDI spec newer than driver', pass: true },
    { name: '/dev/char NVIDIA symlinks', pass: true },
    { name: 'nvidia_uvm module loaded', pass: true },
  ],
};

const warningPreflight = {
  status: 'warning' as const,
  checks: [
    { name: 'CDI spec exists', pass: true },
    { name: 'CDI spec newer than driver', pass: true },
    {
      name: '/dev/char NVIDIA symlinks',
      pass: false,
      fixCommand: 'sudo nvidia-ctk system create-dev-char-symlinks --create-all',
      docsUrl: 'https://github.com/NVIDIA/nvidia-container-toolkit/issues/48',
    },
    { name: 'nvidia_uvm module loaded', pass: true },
  ],
};

describe('GpuHealthCard', () => {
  it('renders nothing when no NVIDIA GPU is detected', () => {
    const { container } = render(
      <GpuHealthCard
        gpuDetected={false}
        preflight={null}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the NVIDIA-only label so non-NVIDIA users are not confused', () => {
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={healthyPreflight}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/GPU Health \(NVIDIA\)/i)).toBeInTheDocument();
  });

  it('green state: healthy preflight + no backend error', () => {
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={healthyPreflight}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/CUDA operational/i)).toBeInTheDocument();
  });

  it('yellow state: preflight has a failed check, no backend error', () => {
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={warningPreflight}
        backendError={null}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/may be misconfigured/i)).toBeInTheDocument();
    expect(
      screen.getByText('sudo nvidia-ctk system create-dev-char-symlinks --create-all'),
    ).toBeInTheDocument();
  });

  it('red state: backend reported unrecoverable; recovery_hint shown verbatim', () => {
    const backendError = {
      status: 'unrecoverable' as const,
      error: 'CUDA unknown error',
      recovery_hint:
        'GPU init failed with error 999 (CUDA unknown). Run scripts/diagnose-gpu.sh.',
    };
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={warningPreflight}
        backendError={backendError}
        onRunDiagnostic={vi.fn()}
      />,
    );
    expect(screen.getByText(/GPU unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/Run scripts\/diagnose-gpu\.sh/)).toBeInTheDocument();
  });

  it('clicking Run Full Diagnostic invokes the prop', async () => {
    const onRun = vi.fn();
    render(
      <GpuHealthCard
        gpuDetected={true}
        preflight={healthyPreflight}
        backendError={null}
        onRunDiagnostic={onRun}
      />,
    );
    const button = screen.getByRole('button', { name: /Run Full Diagnostic/i });
    button.click();
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the test file — it should fail with import error**

```bash
cd dashboard
npx vitest run components/views/__tests__/GpuHealthCard.test.tsx
```

Expected: FAIL with `Cannot find module '../GpuHealthCard'`.

---

## Task 12: Implement `GpuHealthCard.tsx`

**Files:**
- Create: `dashboard/components/views/GpuHealthCard.tsx`

- [ ] **Step 1: Create the component**

Create `dashboard/components/views/GpuHealthCard.tsx`:

```tsx
import React, { useState } from 'react';

export interface GpuPreflightCheckProp {
  name: string;
  pass: boolean;
  fixCommand?: string;
  docsUrl?: string;
}

export interface GpuPreflightProp {
  status: 'healthy' | 'warning' | 'unknown';
  checks: GpuPreflightCheckProp[];
}

export interface GpuBackendErrorProp {
  status: 'unrecoverable';
  error: string;
  recovery_hint?: string;
}

export interface GpuHealthCardProps {
  gpuDetected: boolean;
  preflight: GpuPreflightProp | null;
  backendError: GpuBackendErrorProp | null;
  onRunDiagnostic: () => void;
}

type CardState = 'green' | 'yellow' | 'red';

function deriveState(
  preflight: GpuPreflightProp | null,
  backendError: GpuBackendErrorProp | null,
): CardState {
  if (backendError && backendError.status === 'unrecoverable') return 'red';
  if (preflight && preflight.status === 'warning') return 'yellow';
  return 'green';
}

const STATE_LABEL: Record<CardState, string> = {
  green: 'GPU healthy — CUDA operational',
  yellow: 'GPU may be misconfigured — server will fall back to CPU',
  red: 'GPU unavailable — fell back to CPU',
};

const STATE_COLOR: Record<CardState, string> = {
  green: '#1f8a3a',
  yellow: '#b88a00',
  red: '#b53030',
};

function CopyableCommand({ cmd }: { cmd: string }): React.ReactElement {
  const [copied, setCopied] = useState(false);
  const handleCopy = (): void => {
    void navigator.clipboard.writeText(cmd).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
      <code
        style={{
          padding: '4px 8px',
          background: '#222',
          color: '#eee',
          borderRadius: 4,
          fontSize: 12,
          flex: 1,
          overflowX: 'auto',
        }}
      >
        {cmd}
      </code>
      <button type="button" onClick={handleCopy} style={{ fontSize: 12 }}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

export function GpuHealthCard({
  gpuDetected,
  preflight,
  backendError,
  onRunDiagnostic,
}: GpuHealthCardProps): React.ReactElement | null {
  if (!gpuDetected) return null;

  const state = deriveState(preflight, backendError);
  const failedChecks = preflight ? preflight.checks.filter((c) => !c.pass) : [];

  return (
    <section
      aria-labelledby="gpu-health-title"
      style={{
        border: `1px solid ${STATE_COLOR[state]}`,
        borderRadius: 6,
        padding: 12,
        marginTop: 12,
      }}
    >
      <h3 id="gpu-health-title" style={{ marginTop: 0, color: STATE_COLOR[state] }}>
        GPU Health (NVIDIA)
      </h3>
      <p style={{ fontSize: 12, marginTop: 0, color: '#888' }}>
        This card appears only on systems with an NVIDIA GPU. AMD / Intel /
        Apple Silicon setups do not need it.
      </p>

      <p style={{ fontWeight: 600 }}>{STATE_LABEL[state]}</p>

      {state === 'red' && backendError?.recovery_hint ? (
        <p
          style={{
            background: '#3a1313',
            padding: 8,
            borderRadius: 4,
            color: '#fbb',
            fontSize: 13,
          }}
        >
          {backendError.recovery_hint}
        </p>
      ) : null}

      {failedChecks.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <p style={{ marginBottom: 4, fontWeight: 500 }}>Failing checks:</p>
          {failedChecks.map((check) => (
            <div key={check.name} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 13 }}>
                ✗ {check.name}
                {check.docsUrl ? (
                  <>
                    {' — '}
                    <a href={check.docsUrl} target="_blank" rel="noopener noreferrer">
                      docs
                    </a>
                  </>
                ) : null}
              </div>
              {check.fixCommand ? <CopyableCommand cmd={check.fixCommand} /> : null}
            </div>
          ))}
        </div>
      ) : null}

      <div style={{ marginTop: 12 }}>
        <button type="button" onClick={onRunDiagnostic}>
          Run Full Diagnostic
        </button>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Run the test file — it should now pass**

```bash
cd dashboard
npx vitest run components/views/__tests__/GpuHealthCard.test.tsx
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add dashboard/components/views/GpuHealthCard.tsx dashboard/components/views/__tests__/GpuHealthCard.test.tsx
git commit -m "feat(dashboard, ui): add GpuHealthCard component (NVIDIA-only, 3 states)

* feat(dashboard, ui): GpuHealthCard.tsx renders only when gpuDetected=true; three states (green/yellow/red) derived from preflight + backend error; failing checks render with copyable fix commands and docs links; recovery_hint from the backend rendered verbatim in the red state; 'Run Full Diagnostic' button wired to a prop callback

* test(dashboard, ui): GpuHealthCard.test.tsx — null render when no GPU, NVIDIA-only label, all three states, copyable command rendering, button click invokes the callback"
```

---

## Task 13: Integrate `GpuHealthCard` into `ServerView.tsx`

**Files:**
- Modify: `dashboard/components/views/ServerView.tsx` — add state for preflight + backend error, render the card.

- [ ] **Step 1: Import the component and add state**

Open `dashboard/components/views/ServerView.tsx`. Near the existing imports (top of file), add:

```typescript
import { GpuHealthCard } from './GpuHealthCard';
```

In the same component-state block where `gpuInfo` is declared (around line 1151), add two new state hooks:

```typescript
  const [gpuPreflight, setGpuPreflight] = useState<{
    status: 'healthy' | 'warning' | 'unknown';
    checks: Array<{
      name: string;
      pass: boolean;
      fixCommand?: string;
      docsUrl?: string;
    }>;
  } | null>(null);
  const [gpuBackendError, setGpuBackendError] = useState<{
    status: 'unrecoverable';
    error: string;
    recovery_hint?: string;
  } | null>(null);
```

- [ ] **Step 2: Fetch the preflight on mount, after `checkGpu` resolves**

Find the `useEffect` block where `api.docker.checkGpu()` is called (around line 1171). At the very end of the `.then((info) => { ... })` callback (just before `.catch`), add:

```typescript
          // Phase 2: run the cheap NVIDIA host preflight whenever an NVIDIA GPU was detected.
          if (info.gpu && api?.docker?.validateGpuPreflight) {
            api.docker
              .validateGpuPreflight()
              .then((p: typeof gpuPreflight) => setGpuPreflight(p))
              .catch(() => setGpuPreflight(null));
          }
```

- [ ] **Step 3: Subscribe to backend GPU error from the existing admin status poll**

Find where the component already polls `/api/admin/status` or reads `app.state.gpu_error` (search for `gpu_error` or `containerStatus`). Wherever the parsed status comes back, branch:

```typescript
  // Pseudo-location: in whatever effect already consumes admin status JSON
  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.server?.getAdminStatus) return;
    let cancelled = false;
    const tick = (): void => {
      api.server
        .getAdminStatus()
        .then((s: { gpu_error?: { status: string; error: string; recovery_hint?: string } }) => {
          if (cancelled) return;
          if (s.gpu_error && s.gpu_error.status === 'unrecoverable') {
            setGpuBackendError({
              status: 'unrecoverable',
              error: s.gpu_error.error,
              recovery_hint: s.gpu_error.recovery_hint,
            });
          } else {
            setGpuBackendError(null);
          }
        })
        .catch(() => {});
    };
    tick();
    const id = window.setInterval(tick, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);
```

If the project already has an existing admin-status hook/store, prefer reusing it. Search for the canonical source with: `grep -rn "gpu_error\|admin.*status" dashboard/src/ dashboard/components/ | head`. The exact wiring may differ — the rule is: when the unrecoverable backend status arrives, set `gpuBackendError`; when it does not, set `null`.

- [ ] **Step 4: Define the run-diagnostic handler**

Inside the `ServerView` component body, add:

```typescript
  const handleRunGpuDiagnostic = (): void => {
    const api = (window as any).electronAPI;
    if (!api?.docker?.runGpuDiagnostic) return;
    api.docker
      .runGpuDiagnostic()
      .then((res: { status: string; logPath?: string; manualCommand?: string }) => {
        if (res.status === 'started' && res.logPath) {
          // Show the log path so the user can tail/inspect it.
          window.alert(
            `GPU diagnostic started.\n\nLog file: ${res.logPath}\n\nTail it with:\n  tail -f "${res.logPath}"`,
          );
        } else if (res.status === 'script-missing' && res.manualCommand) {
          window.alert(
            `Diagnostic script not bundled. Run it manually:\n\n  ${res.manualCommand}`,
          );
        } else if (res.status === 'unsupported') {
          window.alert('GPU diagnostic is for Linux NVIDIA hosts only.');
        }
      })
      .catch(() => {
        window.alert('Failed to start GPU diagnostic — see console.');
      });
  };
```

(`window.alert` is the simplest first cut. A later iteration can replace it with a proper modal if the UX needs it — but it satisfies the spec's "surface the log path" requirement.)

- [ ] **Step 5: Render the card**

Find the JSX section where the existing setup checklist or system-status area lives (around the same area where `setupChecks` is rendered). Add the card adjacent to it, gated on Linux + NVIDIA:

```tsx
        {process.platform === 'linux' && (gpuInfo?.gpu ?? false) && (
          <GpuHealthCard
            gpuDetected={true}
            preflight={gpuPreflight}
            backendError={gpuBackendError}
            onRunDiagnostic={handleRunGpuDiagnostic}
          />
        )}
```

- [ ] **Step 6: Type-check the dashboard**

```bash
cd dashboard
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 7: Run the full dashboard test suite**

```bash
cd dashboard
npx vitest run
```

Expected: all tests pass (the new `GpuHealthCard.test.tsx` already covered the component; the integration into `ServerView.tsx` doesn't add new tests since the card is gated on a runtime condition).

- [ ] **Step 8: UI contract check (per project CLAUDE.md)**

```bash
cd dashboard
npm run ui:contract:extract && npm run ui:contract:build && \
  node scripts/ui-contract/validate-contract.mjs --update-baseline && \
  npm run ui:contract:check
```

Expected: passes; baseline updated to reflect the new card classes.

- [ ] **Step 9: Commit**

```bash
git add dashboard/components/views/ServerView.tsx dashboard/ui-contract/
git commit -m "feat(dashboard, server-view): mount GpuHealthCard with backend recovery_hint and full-diagnostic action

* feat(dashboard, server-view): ServerView.tsx now fetches docker.validateGpuPreflight() after checkGpu resolves and polls /api/admin/status for app.state.gpu_error; the result drives the new GpuHealthCard in three states. Card is gated on process.platform === 'linux' && gpuInfo.gpu so AMD/Intel/Apple Silicon installs never see it.

* feat(dashboard, server-view): 'Run Full Diagnostic' button calls docker.runGpuDiagnostic() and surfaces the log path / manual command via a window.alert (placeholder UI; can be promoted to a modal later)

* chore(ui-contract): refresh contract baseline for the new GpuHealthCard classes"
```

---

# Phase 2 — Verification

## Task 14: End-to-end verification

- [ ] **Step 1: Run the full backend test suite**

```bash
cd server/backend
../../build/.venv/bin/pytest tests/ -v --tb=short
```

Expected: all tests pass; no regressions in `test_audio_utils.py` or elsewhere.

- [ ] **Step 2: Run the full dashboard test suite**

```bash
cd dashboard
npx vitest run
```

Expected: all tests pass — including the new `dockerManagerGpuPreflight.test.ts` and `GpuHealthCard.test.tsx`.

- [ ] **Step 3: Run the diagnostic script on the developer's own machine**

```bash
bash scripts/diagnose-gpu.sh
```

Expected: 11 checks complete; the user inspects the `gpu-diagnostic-<timestamp>.log` file and applies any indicated host fix.

- [ ] **Step 4: Manual UI smoke test (Linux + NVIDIA only)**

```bash
cd dashboard
npm run dev:electron
```

Expected:
- The Server tab shows the **GPU Health (NVIDIA)** card.
- On a healthy host: card is green.
- After artificially deleting `/dev/char` symlinks (e.g., `sudo rm /dev/char/195:*` — only do this in a disposable VM), restart the dashboard: card turns yellow with the `nvidia-ctk system create-dev-char-symlinks` command shown in a copyable code block.
- Clicking **Run Full Diagnostic**: an alert appears with the log path; the file `/tmp/gpu-diagnostic-<ts>.log` exists and contains the script's output.

- [ ] **Step 5: Verify the card does NOT appear on non-NVIDIA setups**

Boot the dashboard on macOS or a Linux machine without an NVIDIA GPU. Confirm: the GpuHealthCard is not rendered at all (no element with title "GPU Health (NVIDIA)" exists).

- [ ] **Step 6: Verify the unrecoverable error log now includes `recovery_hint`**

Trigger an artificial unrecoverable state (mock `torch.cuda.init` to raise `"CUDA unknown error"` repeatedly, or simulate by running on a host where the container cannot see the GPU) and grep the server log:

```bash
docker logs transcriptionsuite-container 2>&1 | grep -A 2 'recovery_hint'
```

Expected: the line `recovery_hint=GPU init failed with error 999 (CUDA unknown). … Run scripts/diagnose-gpu.sh on the host …` appears in the structured log output.

---

## Self-review checklist

(Worker should run this checklist after completing all tasks.)

- [ ] **Spec coverage** — every section of the design doc maps to a task:
  - Spec §3 (Phase 1 script + README) → Tasks 1–2.
  - Spec §4.1 (backend `recovery_hint`) → Tasks 3–5.
  - Spec §4.2 (`validateGpuPreflight` preflight) → Tasks 6–8.
  - Spec §4.3 (`GpuHealthCard` on Server tab + Run Full Diagnostic) → Tasks 9–13.
  - Spec §4.4 (cross-platform: card hidden on macOS/Windows) → covered by gating in Task 13 step 5 + tests in Task 11.
  - Spec §4.5 (acceptance criteria) → Task 14 covers each.
- [ ] **No placeholders** — every task contains the actual code; no "TBD" / "see other task" / "implement appropriate" phrasing.
- [ ] **Type consistency** — `GpuPreflightResult` shape is identical in `dockerManager.ts` (Task 7), `preload.ts` (Task 8 step 3), and `GpuHealthCard.tsx` (Tasks 11–12). `RunGpuDiagnosticResult` shape is identical between `dockerManager.ts` (Task 10 step 1) and `preload.ts` (Task 10 step 3).
- [ ] **Commit cadence** — every task ends with a commit; commit messages follow the project style in `CLAUDE.md` (lowercase scope, `feat/fix/chore/etc(area)` prefix).
