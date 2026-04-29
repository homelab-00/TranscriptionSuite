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
