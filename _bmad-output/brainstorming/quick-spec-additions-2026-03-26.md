# Quick-Spec Additions (2026-03-26)

Items to fold into the "CPU Fallback Model Loading + GPU Diagnostics" quick-spec.

---

## Addition 1: CUDA Root Cause — Investigation Complete

> Moves "Fixing the actual CUDA root cause" from Out of Scope to resolved.

### Finding: Driver Context Poisoning (Confirmed)

Reboot fixed the CUDA error 999. Same venv, same torch 2.8.0+cu129, same Docker config — only variable was host driver state. The NVIDIA driver retained stale CUDA context table entries from a prior container crash, preventing new `cuCtxCreate()` calls while NVML-based queries (nvidia-smi) continued working.

**Eliminated:** torch/CUDA version mismatch, missing `/dev/nvidia-uvm`.

**Full writeup:** `_bmad-output/brainstorming/brainstorming-session-2026-03-26-cuda-rca.md`

### Spec Items to Add

**P1 — Prevent recurrence:**

1. **NVIDIA Persistence Mode documentation** — Document `sudo nvidia-smi -pm 1` as recommended host setup for container GPU workloads. Prevents the lazy-unload cycle that leaves dirty driver state. Add to README troubleshooting section.

2. **Startup diagnostic logging** — Before CUDA health check, log a single structured line with: `torch.__version__`, `torch.version.cuda`, device nodes present in container (`ls /dev/nvidia*`), and driver version from nvidia-smi. Makes future failures immediately diagnosable without a brainstorming session.

3. **Health check retry for transient errors** — Post-reboot, the health check returned `no_cuda` (non-999 RuntimeError) but CUDA worked 175ms later when ModelManager ran. Add a single 500ms retry for non-999 RuntimeErrors before declaring `no_cuda`.

**P2 — Recovery documentation:**

4. **"GPU stuck" troubleshooting entry** — If CUDA fails but nvidia-smi works: reboot the host. If frequent, enable Persistence Mode. Mention `nvidia-smi --gpu-reset` as advanced option with multi-consumer warnings.

### Secondary Finding: Health Check Transient Gap

Post-reboot log showed `CUDA health check: no_cuda` followed immediately by `GPU available with 11.62 GB memory`. The health check caught a transient init failure that self-resolved. Current code is resilient (the `no_cuda` path doesn't set `_cuda_probe_failed`), but the status string is misleading. Item 3 above addresses this.

---

## Addition 2: Paste-at-Cursor — Terminal Shortcut (Feasible)

> New In-Scope item.

### Problem

On Linux terminals, `Ctrl+V` doesn't paste — terminals use `Shift+Ctrl+V`. Current paste-at-cursor blindly sends `Ctrl+V` regardless of the active window, so pasting into a terminal fails silently (or worse, sends a control character).

### Solution

Detect if the active window is a terminal emulator before sending the paste keystroke. If so, send `Shift+Ctrl+V` instead of `Ctrl+V`.

### Implementation

**File:** `dashboard/electron/pasteAtCursor.ts`

1. Add a terminal window class blocklist: `konsole`, `kitty`, `alacritty`, `foot`, `wezterm`, `gnome-terminal-server`, `xterm`, `tilix`, `terminator`, `xfce4-terminal`, `mate-terminal`, `sakura`, `st`
2. Before keystroke simulation, detect the active window class:
   - **X11:** `xdotool getactivewindow getwindowclassname` (already available as fallback tool)
   - **KDE Wayland:** `gdbus call --session --dest org.kde.KWin --object-path /KWin --method org.kde.KWin.activeWindow` (returns resource class)
   - **Other Wayland compositors:** Fall back to `Ctrl+V` (no standard protocol for active window introspection)
3. If window class matches terminal list, use shifted variant:
   - `wtype -M ctrl -M shift v -m shift -m ctrl`
   - `xdotool key --clearmodifiers ctrl+shift+v`
   - `ydotool key 29:1 42:1 47:1 47:0 42:0 29:0` (Ctrl+Shift+V raw keycodes)

**Scope:** Linux only. macOS/Windows paste commands already work in terminals (`Cmd+V` / `Ctrl+V`).

---

## Addition 3: Paste-at-Cursor — Text Field Safety (Limited Feasibility)

> Recommend as P2 or future work with documented limitations.

### Problem

If the user's cursor is over a non-text target (e.g. desktop, file manager) when transcription completes, paste-at-cursor sends `Ctrl+V` into the wrong place — potentially pasting clipboard content as a file operation or doing nothing confusing.

### Feasibility Assessment

**Wayland fundamentally prevents reliable text field detection.** The security model deliberately blocks apps from inspecting focused window content type. There is no standard Wayland protocol for "what widget type has focus in the active window."

**What IS feasible: a blocklist approach.**

Detect known window classes that definitely can't accept text paste and skip the paste for those:

| Window Class | Application | Why Skip |
|---|---|---|
| `org.kde.dolphin` | KDE file manager | Ctrl+V = file paste |
| `org.kde.plasmashell` | KDE desktop/panel | No text input |
| `org.gnome.Nautilus` | GNOME file manager | Ctrl+V = file paste |
| `pcmanfm` | PCManFM file manager | Ctrl+V = file paste |
| `thunar` | XFCE file manager | Ctrl+V = file paste |

**Detection mechanism:** Same as Addition 2 — query active window class via `xdotool` (X11) or KWin D-Bus (KDE Wayland).

**Limitations:**
- Only works for known applications (blocklist, not allowlist)
- Desktop-environment-specific on Wayland (no standard protocol)
- Can't detect "cursor is in a text field" within an arbitrary GUI app
- Allowlist approach (only paste into known-good targets) would be too restrictive

### Recommendation

Add as P2 with the blocklist approach. The terminal detection (Addition 2) is the higher-value item. The blocklist can be expanded over time based on user reports.
