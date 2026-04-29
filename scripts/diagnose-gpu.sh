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
