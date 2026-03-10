<p align="left">
  <img src="assets/logo_wide_readme.png" alt="TranscriptionSuite logo" width="680">
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
dashboard + Python backend with
multi-backend STT (Whisper, NVIDIA NeMo,
VibeVoice-ASR), NVIDIA GPU acceleration
or CPU mode. Dockerized for fast setup.
</pre>
          </td>
        </tr>
      </table>
    </td>
    <td align="left" valign="top" width="280px">
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

https://github.com/user-attachments/assets/f63ee730-de9a-4a55-b0ab-e342b30905a4

</div>

---

## Table of Contents
 
## Table of Contents

 - [1. Introduction](#1-introduction)
  - [1.1 Features](#11-features)
  - [1.2 Screenshots](#12-screenshots)
  - [1.3 Short Tour](#13-short-tour)
 - [2. Installation](#2-installation)
   - [2.1 Prerequisites](#21-prerequisites)
   - [2.2 Download the Dashboard app](#22-download-the-dashboard-app)
     - [2.2.1 Linux AppImage Prerequisites (Linux only)](#221-linux-appimage-prerequisites-linux-only)
     - [2.2.2 Verify Download with Kleopatra (optional)](#222-verify-download-with-kleopatra-optional)
   - [2.3 Setting Up the Server](#23-setting-up-the-server)
 - [3. Remote Connection](#3-remote-connection)
   - [3.1 Option A: Tailscale (recommended)](#31-option-a-tailscale-recommended)
     - [Server Machine Setup](#server-machine-setup)
   - [3.2 Option B: LAN (same local network)](#32-option-b-lan-same-local-network)
 - [4. License](#4-troubleshooting)
 - [5. Technical Info](#5-technical-info)
 - [6. License](#6-license)
 - [7. Acknowledgments](#7-acknowledgments)

---

## 1. Introduction

### 1.1 Features

- **100% Local**: *Everything* runs on your own computer, the app doesn't need internet beyond the initial setup*
- **Multiple Models available**: *WhisperX* (all three sizes of the [`faster-whisper`](https://huggingface.co/Systran/faster-whisper-large-v3) models), NVIDIA NeMo [*Parakeet v3*](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)/[*Canary v2*](https://huggingface.co/nvidia/canary-1b-v2), and [*VibeVoice-ASR*](https://huggingface.co/microsoft/VibeVoice-ASR) models are supported
- **Speaker Diarization**: Speaker identification & diarization (subtitling) for all three model families; Whisper and Nemo use PyAnnote for diarization while VibeVoice does it by itself
- **Parallel Processing**: If your VRAM budget allows it, transcribe & diarize a recording at the same time - speeding up processing time significantly
- **Truly Multilingual**: Whisper supports [90+ languages](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py); NeMo Parakeet/Canary support [25 European languages](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3); VibeVoice supports [50 languages](https://huggingface.co/microsoft/VibeVoice-ASR)
- **Longform Transcription**: Record as long as you want and have it transcribed in seconds; either using your mic or the system audio
- **Live Mode**: Real-time sentence-by-sentence transcription for continuous dictation workflows (Whisper-only currently)
- **Global Keyboard Shortcuts**: System-wide shortcuts & paste-at-cursor functionality
- **Remote Access**: Securely access your desktop at home running the model from anywhere
  (utilizing Tailscale) or share it on your local network via LAN
- **Audio Notebook**: An Audio Notebook mode, with a calendar-based view,
  full-text search, and LM Studio integration (chat with the AI about your notes)


📌*Half an hour of audio transcribed in under a minute with Whisper (RTX 3060)!*

**All transcription processing runs entirely on your own computer — your audio never leaves your machine. Internet is only needed to download model weights on first use (STT models, PyAnnote diarization, and wav2vec2 alignment models); all weights are cached locally in a Docker volume and no further internet access is required after that.*

### 1.2 Screenshots

<div align="center">

| Session Tab | Notebook Tab |
|:-----------:|:------------:|
| ![Session Tab](assets/shot-1.png) | ![Notebook Tab](assets/shot-2.png) |

| Audio Note View | Server Tab |
|:---------------:|:----------:|
| ![Audio Note View](assets/shot-3.png) | ![Server Tab](assets/shot-4.png) |

</div>

### 1.3 Short Tour

<div align="center">

https://github.com/user-attachments/assets/688fd4b2-230b-4e2f-bfed-7f92aa769010

</div>

---

## 2. Installation

### 2.1 Prerequisites

To begin with, you need to install Docker (or Podman).

> *Both are supported; the dashboard and shell scripts auto-detect which runtime is available (Docker is checked first, then Podman).*

**Linux (Docker):**

1. Install Docker Engine
    * For Arch run `sudo pacman -S --needed docker`
    * For other distros refer to the [Docker documentation](https://docs.docker.com/engine/install/)
2. Add your user to the `docker` group so the app can talk to Docker without `sudo`:
    ```bash
    sudo usermod -aG docker $USER
    ```
    Then **log out and back in** (or reboot) for the change to take effect.
3. Install NVIDIA Container Toolkit (for GPU mode)
    * Refer to the [NVIDIA documentation](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
    * Not required if using CPU mode

**Linux (Podman):**

1. Install Podman (4.7+ required for `podman compose` support)
    * For Arch run `sudo pacman -S --needed podman`
    * For Fedora/RHEL: Podman is pre-installed
    * For other distros refer to the [Podman documentation](https://podman.io/docs/installation)
2. For GPU mode, configure CDI (Container Device Interface):
    ```bash
    sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
    ```
    * Requires nvidia-container-toolkit 1.14+
    * Not required if using CPU mode

**Windows:**
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 backen (during installation, if presented with the option, make sure the *'Use WSL 2 instead of Hyper-V'* checkbox is enabled).
After installation to make sure it's enabled, run `wsl --list --verbose` - if the number is 2, Docker is using the WSL 2 backend.
2. Install NVIDIA GPU driver with WSL support (standard NVIDIA gaming drivers work fine)
    * Not required if using CPU mode

**macOS:**
1. Install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/) or [Podman Desktop](https://podman-desktop.io/)
2. GPU mode is not available on macOS — the server runs in CPU mode automatically

### 2.2 Download the Dashboard app

Before doing anything else, you need to download the Dashboard app for your platform from the [Releases](https://github.com/homelab-00/TranscriptionSuite/releases) page.
This is just the frontend, no models or packages are downloaded yet.

>* *Linux and Windows builds are x64; macOS is arm64*
>* *Each release artifact includes an gpg signature by my key (`.sig`)*

##### 2.2.1 Linux AppImage Prerequisites (Linux only)

AppImages require **FUSE 2** (`libfuse.so.2`), which is not installed by default on distros that ship with GNOME (both Fedora & Arch KDE worked fine out of the box). If you see `dlopen(): error loading libfuse.so.2`, install the appropriate package:

| Distribution | Package | Install Command |
|---|---|---|
| Ubuntu 22.04 / Debian | `libfuse2` | `sudo apt install libfuse2` |
| Ubuntu 24.04+ | `libfuse2t64` | `sudo apt install libfuse2t64` |
| Fedora | `fuse-libs` | `sudo dnf install fuse-libs` |
| Arch Linux | `fuse2` | `sudo pacman -S fuse2` |

> **Sandbox note:** The AppImage automatically disables Chromium's SUID sandbox
> (`--no-sandbox`) since the AppImage squashfs mount cannot satisfy its permission
> requirements. This is the standard approach for Electron-based AppImages and does
> not affect application security.

##### 2.2.2 Verify Download with Kleopatra (optional)

1. Download both files from the same release:
   - installer/app (`.AppImage`, `.exe` or `.dmg`)
   - matching signature file (`.sig`)
2. Install Kleopatra: https://apps.kde.org/kleopatra/
3. Import the public key in Kleopatra from this repository:
   - [`docs/assets/homelab-00_0xBFE4CC5D72020691_public.asc`](assets/homelab-00_0xBFE4CC5D72020691_public.asc)
4. In Kleopatra, use `File` -> `Decrypt/Verify Files...` and select the downloaded `.asc` signature.
5. If prompted, select the corresponding downloaded app file. Verification should report a valid signature.

### 2.3 Setting Up the Server

We're now ready to start the server. This process includes two parts: downloading the Docker image and starting a Docker container based off of that image.

1. *Download the image*: Using the Sidebar on the left, head over to the Server tab and click the button 'Fetch Fresh Image'
2. *Starting the container*: Scroll down a bit and click the 'Start Local' button in the #2 box
3. *Initial setup - models, diarization*: A series of prompts will ask you for which models you want to download to begin with, and if you want to enable diarization (entering your HuggingFace token and accepting the [terms of the model](https://huggingface.co/pyannote/speaker-diarization-community-1) is required)
4. **Wait** - Initial startup can take a long time, even on newer hardware and fast internet speeds; we're talking 10-20 minutes with reasonable specs though, not hours; you'll know it's done when the server status light turns green
5. **Start the client**: Head to the Session tab and click on the 'Start Local' button inside the Client Link box - if it turns green you're ready to roll!

<br>

Notes:
* *Settings are saved to:*
*- Linux: `~/.config/TranscriptionSuite/`*
*- Windows: `%APPDATA%\TranscriptionSuite\`*
*- macOS: `~/Library/Application Support/TranscriptionSuite/`*

* *GNOME note: The [AppIndicator](https://extensions.gnome.org/extension/615/appindicator-support/) extension is required for system tray support.*

* *Docker vs Podman:*
*TranscriptionSuite supports both Docker and Podman. The dashboard and CLI scripts auto-detect which runtime is available. For GPU mode with Podman, ensure CDI is configured (`sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`).*
*Podman 4.7+ is required for `podman compose` support.*


---

## 3. Remote Connection

TranscriptionSuite supports remote transcription where a **server machine** (with a
GPU) runs the Docker container and a **client machine** connects to it via the
Dashboard app. Two connection profiles are available:

| Profile | Use Case | Network Requirement |
|---------|----------|---------------------|
| **Tailscale** | Cross-network / internet (recommended) | Both machines on the same [Tailnet](https://tailscale.com/) |
| **LAN** | Same local network, no Tailscale needed | Both machines on the same LAN / subnet |

Both profiles use **HTTPS + token authentication**. The only difference is *how* the
client reaches the server and *where* the TLS certificates come from.

**Architecture overview:**

```
┌─────────────────────────┐         HTTPS (port 9786)        ┌─────────────────────────┐
│      Server Machine     │◄────────────────────────────────►│      Client Machine     │
│                         │         + Auth Token             │                         │
│  • Runs the Dashboard   │                                  │  • Runs the Dashboard   │
│  • Clicks "Start Remote"│         Tailscale Tunnel         │  • Settings → Client →  │
│  • Has TLS certificates │         ── or ──                 │    "Use remote server"  │
│  • Has the GPU          │         LAN connection           │  • No GPU needed        │
└─────────────────────────┘                                  └─────────────────────────┘
```

**Security model:**

| Layer | Protection |
|-------|------------|
| **Tailscale Network** *(Tailscale profile)* | Only devices on your Tailnet can reach the server |
| **TLS/HTTPS** | All traffic encrypted with certificates |
| **Token Authentication** | Required for all API requests in remote mode |

### 3.1 Option A: Tailscale (recommended)

Use this when the server and client are on **different networks** (e.g., home
server ↔ work laptop), or when you want Tailscale's zero-config networking
and automatic DNS.

#### Server Machine Setup

**Step 1 — Install & Authenticate Tailscale**

1. Install Tailscale: [tailscale.com/download](https://tailscale.com/download)
2. Authenticate: `sudo tailscale up` (Linux) or via the Tailscale app (Windows/macOS)
3. Go to [Tailscale Admin Console](https://login.tailscale.com/admin) → **DNS** tab
4. Enable **MagicDNS** and **HTTPS Certificates**

Your DNS settings should look like this:

![Tailscale DNS Settings](assets/tailscale-dns-settings.png)

**Step 2 — Generate TLS Certificates** *(server machine only)*

```bash
# Replace with your actual machine name + tailnet
sudo tailscale cert your-machine.your-tailnet.ts.net
```

This produces two files: `your-machine.your-tailnet.ts.net.crt` and
`your-machine.your-tailnet.ts.net.key`. Move and rename them to the standard
location so the app can find them without config changes:

*(To change the default location, edit `remote_server.tls.host_cert_path` and
`host_key_path` in `config.yaml`.)*

**Linux:**
```bash
mkdir -p ~/.config/Tailscale
mv your-machine.your-tailnet.ts.net.crt ~/.config/Tailscale/my-machine.crt
mv your-machine.your-tailnet.ts.net.key ~/.config/Tailscale/my-machine.key
sudo chown $USER:$USER ~/.config/Tailscale/my-machine.*
chmod 600 ~/.config/Tailscale/my-machine.key
```

**Windows (PowerShell):**
```powershell
mkdir "$env:USERPROFILE\Documents\Tailscale" -Force
mv your-machine.your-tailnet.ts.net.crt "$env:USERPROFILE\Documents\Tailscale\my-machine.crt"
mv your-machine.your-tailnet.ts.net.key "$env:USERPROFILE\Documents\Tailscale\my-machine.key"
```

For Windows, also update the certificate paths in `config.yaml`:
```yaml
remote_server:
  tls:
    host_cert_path: "~/Documents/Tailscale/my-machine.crt"
    host_key_path: "~/Documents/Tailscale/my-machine.key"
```

> **Note:** Tailscale HTTPS certificates are issued for `.ts.net` hostnames, so
> MagicDNS must be enabled in your Tailnet.

**Step 3 — Start the Server in Remote Mode**

1. Open the Dashboard on the server machine
2. Navigate to the **Server** view
3. Click **Start Remote**
4. Wait for the container to become healthy (green status)

On the first remote start, an admin **auth token** is generated automatically.
You can find it in the Server view's "Auth Token" field, or in the container logs:
```bash
docker compose logs | grep "Admin Token:"
```

Copy this token — you'll need it on the client machine.

> **Tailscale hostname:** Once the server is running, the Server view displays the
> machine's Tailscale FQDN (e.g., `desktop.tail1234.ts.net`) with a copy button.
> Use this exact hostname when configuring clients — don't enter just the tailnet
> suffix (e.g., `tail1234.ts.net`).

**Step 4 — Open the Firewall Port (Linux)**

If the server machine runs a firewall, port 9786 must be open for
remote clients to reach the server. Without this, connections silently time out.

| Distribution | Command |
|---|---|
| **Ubuntu / Debian** (`ufw`) | `sudo ufw allow 9786/tcp comment 'TranscriptionSuite Server'` |
| **Fedora GNOME / Fedora KDE** (`firewalld`) | `sudo firewall-cmd --permanent --add-port=9786/tcp && sudo firewall-cmd --reload` |

The dashboard will show a firewall warning banner on the Server view if it
detects the port may be blocked.

> **Note:** This step is only needed on Linux with an active firewall. Windows and
> macOS do not typically block Docker ports by default.

#### Client Machine Setup

1. Install Tailscale on the client machine and sign in with the **same account**
   as the server machine (so both devices are on the same Tailnet)
2. Open the Dashboard on the client machine
3. Go to **Settings** → **Client** tab
4. Enable **"Use remote server instead of local"**
5. Select **Tailscale** as the remote profile
6. Enter the server's **full Tailscale hostname** in the host field
   (e.g., `my-machine.tail1234.ts.net`) — copy it from the Server view on the
   server machine
7. Set port to **`9786`**
8. **Use HTTPS** will be automatically enabled
9. Paste the **auth token** from the server into the Auth Token field
10. Close the Settings modal — the client now connects to the remote server

> **Tip:** The client machine does *not* need certificates, Docker, or a GPU.
> It only needs Tailscale running and a valid auth token.

> **Common mistake:** Enter the **full machine hostname** (e.g.,
> `desktop.tail1234.ts.net`), not just the tailnet name (`tail1234.ts.net`).
> The Settings modal will warn you if it detects a bare tailnet name without a
> machine prefix.

### 3.2 Option B: LAN (same local network)

Use this when both machines are on the **same local network** and you don't want
to use Tailscale. This is common for home-lab setups or office environments.

LAN mode uses the same HTTPS + token authentication as Tailscale mode — the only
differences are the hostname (LAN IP or local DNS name instead of a `.ts.net`
address) and the certificate source (self-signed, local CA, or other locally
trusted certificate instead of a Tailscale-issued one).

#### Server Machine Setup

**Step 1 — TLS Certificate**

LAN mode requires a TLS certificate. The dashboard **auto-generates** a
self-signed certificate on the first remote start if none exists, covering
`localhost` and all detected LAN IP addresses. No manual steps are needed in
most cases.

> **Custom certificate (optional):** If you prefer to use your own certificate
> (e.g., from an internal CA), place it at the paths in `config.yaml` under
> `remote_server.tls.lan_host_cert_path` / `lan_host_key_path`
> (defaults: `~/.config/TranscriptionSuite/lan-server.crt` / `.key` on Linux,
> `~/Documents/TranscriptionSuite/lan-server.crt` / `.key` on Windows).

**Step 2 — Start the Server in Remote Mode**

Same as Tailscale above:
1. Open the Dashboard, go to **Server** view, click **Start Remote**
2. Copy the auth token once the container is healthy

**Step 3 — Open the Firewall Port (Linux)**

Same as Tailscale above — if a firewall is active:

| Distribution | Command |
|---|---|
| **Ubuntu / Debian** (`ufw`) | `sudo ufw allow 9786/tcp` |
| **Fedora GNOME / Fedora KDE** (`firewalld`) | `sudo firewall-cmd --permanent --add-port=9786/tcp && sudo firewall-cmd --reload` |

#### Client Machine Setup

1. Open the Dashboard on the client machine
2. Go to **Settings** → **Client** tab
3. Enable **"Use remote server instead of local"**
4. Select **LAN** as the remote profile
5. Enter the server's **LAN IP or hostname** (e.g., `192.168.1.100`)
6. Set port to **`9786`**
7. **Use HTTPS** will be automatically enabled
8. Paste the **auth token** from the server
9. Close Settings — the client now connects over your local network

> **Note on Kubernetes / custom deployments:** If you run the server container
> directly (e.g., via Kubernetes or your own Docker setup), you can still use the
> LAN profile on the client. Just point the LAN host at your load balancer or
> service IP. The server image is available at
> `ghcr.io/homelab-00/transcriptionsuite-server`. Ensure `TLS_ENABLED=true` and
> the certificate/key are mounted at `/certs/cert.crt` and `/certs/cert.key`
> inside the container.

---

## 4. Troubleshooting

As with most things, the first thing to try is turning them off and on again. Stop the server/client, quit the app and then try again.

The next step is to start deleting things. The safest choice is deleting *everything*, but that means having to redownload everything and losing whatever recordings you've saved in the Notebook (unless you create a backup). Volumes 'data' & 'models' don't usually need to be removed for example.

Controls for all these actions can be found in the Server tab. Here you can remove the container, image, and volumes individually or use the big red button at the bottom (that can also remove your config folder).

---

## 5. Technical Info

For more information about the technical aspects of the project, check out [README_DEV](README_DEV.md).

---

## 6. License

GNU General Public License v3.0 or later (GPLv3+) — See [LICENSE](../LICENSE).

---

## 7. Acknowledgments

- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [WhisperX](https://github.com/m-bain/whisperX)
- [NVIDIA NeMo](https://github.com/NVIDIA/NeMo)
- [VibeVoice-ASR](https://github.com/microsoft/VibeVoice)
- [CTranslate2](https://github.com/OpenNMT/CTranslate2)
- [PyAnnote Audio](https://github.com/pyannote/pyannote-audio)
- [Tailscale](https://tailscale.com/)
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) - For inspiring this project!
