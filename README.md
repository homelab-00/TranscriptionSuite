<p align="left">
  <img src="./build/assets/logo_wide_readme.png" alt="TranscriptionSuite logo" width="680">
</p>

<table width="100%">
  <tr>
    <td valign="top">
      <table>
        <tr>
          <td width="375px">
<pre>
A fully local and private Speech-To-Text
app with cross-platform support, speaker
diarization, Audio Notebook mode,
LM Studio integration, and both longform
and live transcription. Electron
dashboard + Python backend powered by
faster-whisper, NVIDIA Parakeet & Canary with
GPU acceleration or CPU mode. The server
is Dockerized for fast setup.
</pre>
          </td>
        </tr>
      </table>
    </td>
    <td align="left" valign="top" width="280px">
      <br>
      <strong>OS Support:</strong><br>
      <img src="https://img.shields.io/badge/Linux-%23FCC624.svg?style=for-the-badge&logo=linux&logoColor=black" alt="Linux">
      <img src="https://img.shields.io/badge/Windows%2011-%230078D4.svg?style=for-the-badge&logo=Windows%2011&logoColor=white" alt="Windows 11"><br>
      Experimental:<br>
      <img src="https://img.shields.io/badge/macOS-000000.svg?style=for-the-badge&logo=apple&logoColor=white" alt="macOS"><br><br>
      <strong>Hardware Acceleration:</strong><br>
      <img src="https://img.shields.io/badge/NVIDIA-Recommended-%2376B900.svg?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA Recommended"><br>
      <img src="https://img.shields.io/badge/CPU-Supported-%230EA5E9.svg?style=for-the-badge" alt="CPU Supported">
    </td>
  </tr>
</table>

<br>

<div align="center">

**Demo**

https://github.com/user-attachments/assets/13063bf9-0e1d-4688-af84-cb21686c7f41

</div>

---

## Table of Contents

- [1. Introduction](#1-introduction)
  - [1.1 Features](#11-features)
  - [1.2 Screenshots](#12-screenshots)
  - [1.3 Important Compatibility Notes](#13-important-compatibility-notes)
- [2. Prerequisites](#2-prerequisites)
  - [2.1 Docker](#21-docker)
- [3. Installation](#3-installation)
  - [3.1 Linux AppImage Prerequisites](#31-linux-appimage-prerequisites)
  - [3.2 Verify Download (Kleopatra)](#32-verify-download-kleopatra)
- [4. First-Time Setup](#4-first-time-setup)
  - [4.1 Settings Overview](#41-settings-overview)
  - [4.2 Starting the Server and Client](#42-starting-the-server-and-client)
- [5. Usage](#5-usage)
  - [5.1 Quick Start](#51-quick-start)
  - [5.2 Dashboard Views](#52-dashboard-views)
  - [5.3 Model and Feature Compatibility](#53-model-and-feature-compatibility)
- [6. Remote Access](#6-remote-access)
  - [6.1 Choose a Remote Profile in the App](#61-choose-a-remote-profile-in-the-app)
  - [6.2 Tailscale Setup (MagicDNS + HTTPS Certificates)](#62-tailscale-setup-magicdns--https-certificates)
  - [6.3 Generate and Place Certificates](#63-generate-and-place-certificates)
  - [6.4 LAN Remote Mode (No Tailscale)](#64-lan-remote-mode-no-tailscale)
- [7. Database & Backups](#7-database--backups)
  - [7.1 Automatic Backups](#71-automatic-backups)
  - [7.2 Manual Backup/Restore in the Dashboard](#72-manual-backuprestore-in-the-dashboard)
  - [7.3 Export Individual Recordings](#73-export-individual-recordings)
- [8. Troubleshooting](#8-troubleshooting)
  - [8.1 Server Won't Start](#81-server-wont-start)
  - [8.2 GPU Not Detected](#82-gpu-not-detected)
  - [8.3 Connection Issues (Remote Mode)](#83-connection-issues-remote-mode)
- [9. License](#9-license)
- [10. Acknowledgments](#10-acknowledgments)

---

## 1. Introduction

### 1.1 Features

- **100% Local & Private**: Audio processing and transcription run on your own machine (internet is only needed for initial installs/model downloads when applicable)
- **Cross-Platform Dashboard**: Electron desktop app for Linux, Windows, and macOS (macOS support is currently marked experimental)
- **GPU + CPU Modes**: NVIDIA CUDA acceleration (recommended) or CPU-only mode for all platforms (including macOS)
- **Multiple ASR Backends (Longform/Static)**: Whisper (faster-whisper), NVIDIA Parakeet, and NVIDIA Canary (NeMo)
- **Longform Transcription**: Record audio and transcribe after stopping the recording
- **Live Mode**: Real-time sentence-by-sentence transcription in the Session view (current v1 implementation uses the whisper/faster-whisper live path)
- **Speaker Diarization**: PyAnnote-based speaker labeling for supported workflows
- **Static File Transcription**: Import audio/video files into a queue with per-file progress and retry support
- **Audio Notebook**: Calendar/search/import workflow with transcript storage, export, and LLM-assisted note workflows
- **LM Studio Integration**: Local LLM chat/summarization with LM Studio support (some features rely on LM Studio-specific endpoints)
- **System Tray Controls**: Quick actions for server, recording, and common dashboard controls
- **Remote Access**: HTTPS + token-authenticated remote usage via Tailscale or a trusted LAN

📌*Half an hour of audio transcribed in under a minute (RTX 3060)!*

### 1.2 Screenshots

<div align="center">

**Session Tab**
![Session Tab](./build/assets/shot-1.png)

**Notebook Tab**
![Notebook Tab](./build/assets/shot-2.png)

**Audio Note View**
![Audio Note View](./build/assets/shot-3.png)

**Server Tab**
![Server Tab](./build/assets/shot-4.png)

</div>

### 1.3 Important Compatibility Notes

- **Live Mode backend support (current v1)**: Live Mode (`/ws/live`) uses the whisper/faster-whisper live path. Do not assume Parakeet/Canary support for Live Mode in the current version.
- **Translation support**: Whisper and Canary support translation flows; Parakeet does not support translation.
- **Remote mode security**: Remote profiles (`Tailscale`, `LAN`) use HTTPS + token authentication.
- **Docker-first server runtime**: The supported server runtime workflow is Docker/Docker Desktop; advanced native-backend runs are documented in `README_DEV.md`.

---

## 2. Prerequisites

### 2.1 Docker

**Linux:**

1. Install Docker Engine
   - Arch: `sudo pacman -S --needed docker`
   - Other distros: see the [Docker Engine install docs](https://docs.docker.com/engine/install/)
2. Add your user to the `docker` group so the app can access Docker without `sudo`:
   ```bash
   sudo usermod -aG docker $USER
   ```
   Then **log out and back in** (or reboot) for the change to take effect.
3. Install NVIDIA Container Toolkit (GPU mode only)
   - See the [NVIDIA Container Toolkit install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
   - Not required for CPU mode

**Windows:**

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 backend
2. Install NVIDIA GPU drivers with WSL support if you want GPU mode
   - Not required for CPU mode

**macOS:**

1. Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
2. GPU mode is not available on macOS; the server runs in CPU mode

---

## 3. Installation

Download the dashboard for your platform from the [Releases](https://github.com/homelab-00/TranscriptionSuite/releases) page:

| Platform | Download | Notes |
|----------|----------|-------|
| **Linux** | `TranscriptionSuite-*-x86_64.AppImage` | May require FUSE 2 (see below) |
| **Windows** | `TranscriptionSuite Setup *.exe` | NSIS installer |
| **macOS** | `TranscriptionSuite-*-arm64.dmg` | Unsigned Apple Silicon build |

Notes:
- Linux and Windows builds are x64
- macOS builds are Apple Silicon (`arm64`)
- Release artifacts include armored detached signatures (`.asc`)

### 3.1 Linux AppImage Prerequisites

AppImages require **FUSE 2** (`libfuse.so.2`). If you see `dlopen(): error loading libfuse.so.2`, install the appropriate package:

| Distribution | Package | Install Command |
|---|---|---|
| Ubuntu 22.04 / Debian | `libfuse2` | `sudo apt install libfuse2` |
| Ubuntu 24.04+ | `libfuse2t64` | `sudo apt install libfuse2t64` |
| Fedora | `fuse-libs` | `sudo dnf install fuse-libs` |
| Arch Linux | `fuse2` | `sudo pacman -S fuse2` |

> **Sandbox note:** The AppImage disables Chromium's SUID sandbox (`--no-sandbox`) because AppImage mounts cannot satisfy the required permissions. This is standard for Electron AppImages.

### 3.2 Verify Download (Kleopatra)

1. Download both files from the same release:
   - the app artifact (`.AppImage`, `.exe`, or `.dmg`)
   - the matching detached signature (`.asc`)
2. Install Kleopatra: https://apps.kde.org/kleopatra/
3. Import the public key from this repository:
   - [`build/assets/homelab-00_0xBFE4CC5D72020691_public.asc`](./build/assets/homelab-00_0xBFE4CC5D72020691_public.asc)
4. In Kleopatra, use `File` -> `Decrypt/Verify Files...` and select the downloaded `.asc` signature.
5. If prompted, select the corresponding downloaded app file. Verification should report a valid signature.

---

## 4. First-Time Setup

Before starting the server and using transcription features, open the **Settings** modal from the sidebar (gear icon).

### 4.1 Settings Overview

The Settings modal has four tabs:

- **App**: General app behavior (notifications, auto-copy, startup/minimize behavior, update checks, etc.)
- **Client**: Connection mode and remote profile settings (`Local`, `Tailscale`, `LAN`) plus auth token
- **Server**: Advanced server settings and config access (including server-side configuration editing flows)
- **Notebook**: Backup and restore actions for the Audio Notebook database

Notebook tab capabilities include:
- Create manual backups
- View available backups with timestamps and sizes
- Restore from a selected backup (with safety backup behavior in the server)

**Dashboard settings are stored in:**
- Linux: `~/.config/TranscriptionSuite/`
- Windows: `%APPDATA%\TranscriptionSuite\`
- macOS: `~/Library/Application Support/TranscriptionSuite/`

### 4.2 Starting the Server and Client

1. Open the **Server** view in the sidebar
2. Click **Pull Image** (first time only, or when updating)
3. Wait for the Docker image download to finish
4. Click **Start Container**
5. Wait for the container health indicator to turn green
6. Switch to the **Session** view to begin recording/transcribing

If the container fails to start, see [Section 8: Troubleshooting](#8-troubleshooting).

---

## 5. Usage

### 5.1 Quick Start

**Longform transcription (Session view):**

1. Select language (or leave on auto detect)
2. Click **Record**
3. Speak / capture audio
4. Click **Stop**
5. Wait for transcription to finish
6. Review/copy/export the result

**Live Mode (Session view):**

1. Enable the **Live Mode** toggle
2. Speak naturally with pauses
3. Watch completed sentences appear in real time
4. Use **Mute/Unmute** to control audio capture
5. Stop Live Mode when finished

**Static file transcription (Notebook -> Import):**

1. Open **Notebook** -> **Import** tab
2. Drag-and-drop or browse for audio/video files
3. Queue one or many files
4. Monitor progress per file (including retry on failure)
5. Completed items are added to the Audio Notebook

### 5.2 Dashboard Views

The dashboard uses sidebar navigation with these main views:

- **Session**
  - Main transcription controls (record/stop, language, translation)
  - Live Mode controls and real-time sentence display
  - Audio visualizer
  - Transcription output and logs
- **Notebook**
  - Calendar view of recordings
  - Search
  - Import queue for files
- **Server**
  - Docker image management
  - Container start/stop/status
  - Runtime mode (GPU/CPU) selection and related server controls
- **Settings**
  - App / Client / Server / Notebook configuration

**System Tray (when supported by your desktop environment):**
- Quick server start/stop
- Quick recording controls
- Open dashboard
- Transcribe file shortcut
- Tray icon reflects server/recording state

Notes:
- Some Linux desktops (for example GNOME) may require an AppIndicator extension for tray support.
- The tray "Transcribe File" flow uses a simplified/pure transcription path (no diarization).

### 5.3 Model and Feature Compatibility

This is the user-facing compatibility summary for the current version.

| Feature | Whisper (faster-whisper) | NVIDIA Parakeet | NVIDIA Canary |
|---------|---------------------------|-----------------|---------------|
| Longform transcription | Yes | Yes | Yes |
| Static file / Notebook upload transcription | Yes | Yes | Yes |
| Speaker diarization (where enabled) | Yes (workflow-dependent) | Yes (workflow-dependent) | Yes (workflow-dependent) |
| Translation (longform/static/notebook) | Yes | No | Yes |
| Live Mode (`/ws/live`, current v1) | **Yes** | **No** | **No** |

Additional notes:
- Parakeet models are ASR-only (no translation).
- Canary supports translation in server-side capabilities, but the current Live Mode path is whisper/faster-whisper only.
- In the UI, some translation toggles may be disabled automatically depending on selected model capabilities.

---

## 6. Remote Access

TranscriptionSuite supports remote use from a client machine to a server machine using either:

- **Tailscale** (Tailnet hostname + Tailscale-issued TLS certificates)
- **LAN** (local hostname/IP + your own trusted TLS certificate)

Remote mode uses layered protections:

| Layer | Protection |
|-------|------------|
| **Network reachability** | Tailscale Tailnet or your trusted local network |
| **TLS/HTTPS** | Encrypted traffic |
| **Token authentication** | Required for API access in remote mode |

### 6.1 Choose a Remote Profile in the App

In **Settings -> Client**:

1. Enable **Use remote server instead of local**
2. Choose **Remote Profile**:
   - **Tailscale**
   - **LAN**
3. Enter the host for that profile
4. Set port to `8443`
5. Enable HTTPS (the UI enforces HTTPS for remote profiles)
6. Paste the auth token from the server

### 6.2 Tailscale Setup (MagicDNS + HTTPS Certificates)

1. Install Tailscale: [tailscale.com/download](https://tailscale.com/download)
2. Sign in / connect the machine to your Tailnet
3. In the [Tailscale Admin Console](https://login.tailscale.com/admin), enable:
   - **MagicDNS**
   - **HTTPS Certificates**

Your DNS settings should look similar to this:

![Tailscale DNS Settings](./build/assets/tailscale-dns-settings.png)

### 6.3 Generate and Place Certificates

Run this on the machine that will host the TranscriptionSuite server.

Generate certificates:

```bash
sudo tailscale cert your-machine.your-tailnet.ts.net
```

You can change the default certificate paths in `config.yaml` (`remote_server.tls.*`), but the app/scripts look for standard locations by default.

**Linux (default path examples):**
```bash
mkdir -p ~/.config/Tailscale
mv your-machine.your-tailnet.ts.net.crt ~/.config/Tailscale/my-machine.crt
mv your-machine.your-tailnet.ts.net.key ~/.config/Tailscale/my-machine.key
sudo chown $USER:$USER ~/.config/Tailscale/my-machine.*
chmod 600 ~/.config/Tailscale/my-machine.key
```

**Windows (PowerShell default path examples):**
```powershell
mkdir "$env:USERPROFILE\Documents\Tailscale" -Force
mv your-machine.your-tailnet.ts.net.crt "$env:USERPROFILE\Documents\Tailscale\my-machine.crt"
mv your-machine.your-tailnet.ts.net.key "$env:USERPROFILE\Documents\Tailscale\my-machine.key"
```

If needed, update `config.yaml` paths to match your certificate location:
- `remote_server.tls.host_cert_path`
- `remote_server.tls.host_key_path`

### 6.4 LAN Remote Mode (No Tailscale)

Use LAN mode when both machines are on the same trusted local network and you prefer not to use Tailscale.

Requirements:

1. A **trusted TLS certificate** for the hostname/IP you will use
2. The server running in **HTTPS/TLS mode** on port `8443`
3. An auth token from the server

Dashboard setup (Client tab):

- Enable **Use remote server instead of local**
- Set **Remote Profile** to **LAN**
- Enter the LAN hostname/IP (for example `192.168.1.50`)
- Set port to `8443`
- Paste the auth token

Notes:
- LAN mode still uses the same HTTPS + token-auth flow as Tailscale mode.
- If you use a proxy/load balancer, it must support WebSocket upgrades for transcription endpoints.
- The client machine must trust the certificate used by the server.

---

## 7. Database & Backups

### 7.1 Automatic Backups

TranscriptionSuite automatically backs up the SQLite database on server startup.

Default behavior (from the shipped server config):
- New backup if the latest backup is older than **1 hour**
- Keep up to **3 backups**
- Store backups under the server data volume (typically `/data/database/backups/` in Docker)

Default config section (`config.yaml`):

```yaml
backup:
    enabled: true
    max_age_hours: 1
    max_backups: 3
```

### 7.2 Manual Backup/Restore in the Dashboard

Open **Settings -> Notebook** to manage backups:

1. Click **Create Backup** to create a manual backup
2. Review the backup list (timestamps and sizes)
3. Select a backup and choose **Restore** when needed

The server performs validation and safety steps during restore (including integrity checks and safety backup behavior).

### 7.3 Export Individual Recordings

You can export individual transcriptions from the Audio Notebook.

Typical flow:

1. Open a recording in the Notebook workflow
2. Choose the export action
3. Select a supported format

Common formats:
- `Text (.txt)` for plain transcript exports
- `SubRip (.srt)` for subtitle-style exports
- `Advanced SubStation Alpha (.ass)` for richer subtitle exports

When diarization is available, exports may include normalized speaker labels (for example `Speaker 1`, `Speaker 2`).

---

## 8. Troubleshooting

### 8.1 Server Won't Start

Check Docker logs first:

```bash
docker compose logs -f
```

Also check:
- Docker Desktop / Docker daemon is running
- You have Docker permissions (Linux `docker` group)
- The image pull completed before starting the container
- TLS certificate paths are valid if using remote HTTPS mode

Optional helper:
- `lazydocker` can make container/log inspection easier if you use Docker frequently.

### 8.2 GPU Not Detected

Verify Docker GPU access:

```bash
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi
```

If GPU mode is not available:
- Switch to **CPU mode** in the dashboard (Server view / runtime mode controls)
- CPU mode works on Linux, Windows, and macOS, but will be slower than GPU mode

Linux-specific checks:
- NVIDIA driver installed
- NVIDIA Container Toolkit installed
- Docker restarted after toolkit install (if needed)

### 8.3 Connection Issues (Remote Mode)

Checklist:

1. Verify Tailscale is connected (if using Tailscale): `tailscale status`
2. Confirm MagicDNS + HTTPS certificates are enabled in Tailscale admin settings
3. Check certificate paths in `config.yaml` (`remote_server.tls.*`)
4. Make sure the dashboard remote profile is correct (`Tailscale` vs `LAN`)
5. Ensure the port is `8443` and HTTPS is enabled in the client settings
6. Confirm the server auth token is correct

If you are using LAN mode:
- Verify the certificate is trusted on the client machine
- Verify any reverse proxy/load balancer supports WebSocket upgrades

For advanced troubleshooting (Docker runtime, deeper DNS/TLS diagnostics, developer workflows), see [README_DEV.md](README_DEV.md).

---

## 9. License

GNU General Public License v3.0 or later (GPLv3+) — see [LICENSE](LICENSE).

---

## 10. Acknowledgments

- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [NVIDIA NeMo](https://github.com/NVIDIA/NeMo) (Parakeet and Canary ASR models)
- [PyAnnote Audio](https://github.com/pyannote/pyannote-audio)
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)
- [Tailscale](https://tailscale.com/)
- [LM Studio](https://lmstudio.ai/)

