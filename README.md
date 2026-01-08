# TranscriptionSuite

<img align="left" style="margin-right: 20px" width="90" height="90" src="./build/assets/logo.svg">

<pre>A comprehensive Speech-to-Text Transcription Suite with Docker-first
architecture. Written in Python, utilizing faster_whisper with
GPU acceleration.
</pre>

## Table of Contents

- [1. Features](#1-features)
- [2. Prerequisites](#2-prerequisites)
  - [2.1 Docker](#21-docker)
  - [2.2 Git](#22-git)
  - [2.3 Verify GPU Support](#23-verify-gpu-support)
- [3. Installation](#3-installation)
  - [3.1 Step 1: Clone the Repository](#31-step-1-clone-the-repository)
  - [3.2 Step 2: Run Setup Script](#32-step-2-run-setup-script)
  - [3.3 Step 3: Configure HuggingFace Token (Optional)](#33-step-3-configure-huggingface-token-optional)
  - [3.4 Step 4: Start the Server (Local Mode)](#34-step-4-start-the-server-local-mode)
  - [3.5 Stop the Server](#35-stop-the-server)
- [4. Remote Access (Optional)](#4-remote-access-optional)
  - [4.1 Step 1: Set Up Tailscale](#41-step-1-set-up-tailscale)
  - [4.2 Step 2: Generate Certificates](#42-step-2-generate-certificates)
  - [4.3 Step 3: Configure TLS Paths](#43-step-3-configure-tls-paths)
  - [4.4 Step 4: Start Server (Remote Mode)](#44-step-4-start-server-remote-mode)
  - [4.5 Step 5: Save the Admin Token (First Run Only)](#45-step-5-save-the-admin-token-first-run-only)
- [5. Remote Access Without MagicDNS](#5-remote-access-without-magicdns)
  - [5.1 Option 1: IP-Only Mode (Recommended)](#51-option-1-ip-only-mode-recommended)
  - [5.2 Option 2: Self-Signed Certificates](#52-option-2-self-signed-certificates)
  - [5.3 Why MagicDNS is Recommended](#53-why-magicdns-is-recommended)
- [6. Dashboard](#6-dashboard)
  - [6.1 First-Time Setup](#61-first-time-setup)
  - [6.2 GNOME Dashboard Dependencies](#62-gnome-dashboard-dependencies)
  - [6.3 KDE Client Dependencies](#63-kde-client-dependencies)
  - [6.4 Usage](#64-usage)
  - [6.5 Docker Server Control](#65-docker-server-control)
  - [6.6 Tray Icon Colors](#66-tray-icon-colors)
  - [6.7 Client Configuration](#67-client-configuration)
- [7. Web Interface](#7-web-interface)
- [8. Database & Backups](#8-database--backups)
- [9. Troubleshooting](#9-troubleshooting)
  - [9.1 Server Won't Start](#91-server-wont-start)
  - [9.2 GPU Not Detected](#92-gpu-not-detected)
  - [9.3 GNOME Tray Icon Not Showing](#93-gnome-tray-icon-not-showing)
  - [9.4 Connection Issues (Remote Mode)](#94-connection-issues-remote-mode)
- [10. Security](#10-security)
- [11. License](#11-license)
- [12. Acknowledgments](#12-acknowledgments)

---

## 1. Features

- **Multilingual**: Supports [90+ languages](https://platform.openai.com/docs/guides/speech-to-text/supported-languages)
- **GPU Accelerated**: NVIDIA GPU support via PyTorch bundled CUDA/cuDNN
- **Long-form Dictation**: Real-time transcription with optional live preview
- **Static File Transcription**: Transcribe audio/video files
- **Speaker Diarization**: PyAnnote-based speaker identification
- **Audio Notebook**: Calendar-based audio notes with full-text search, AI chat about your notes via LM Studio
- **Remote Access**: Secure access via Tailscale + TLS from anywhere
- **Cross-Platform Clients**: Native system tray apps for KDE, GNOME, and Windows
- **GPU Memory Management**: Toggle models on/off from tray menu to free VRAM when not in use

📌*Half an hour of audio transcribed in under a minute (RTX 3060)!*

---

## 2. Prerequisites

### 2.1 Docker

**Linux:**
```bash
# Install Docker Engine
# See: https://docs.docker.com/engine/install/

# Install NVIDIA Container Toolkit (for GPU support)
# See: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
```

**Windows:**
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 backend
2. Install NVIDIA GPU driver with WSL support

### 2.2 Git

**Linux:**
```bash
# Debian/Ubuntu
sudo apt install git

# Arch Linux
sudo pacman -S --needed git
```

**Windows:**
Download and install [Git for Windows](https://git-scm.com/download/win)

### 2.3 Verify GPU Support

```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

---

## 3. Installation

### 3.1 Step 1: Clone the Repository

**From GitHub:**
```bash
git clone https://github.com/homelab-00/TranscriptionSuite.git
cd TranscriptionSuite
```

**Or from GitLab:**
*Note: GitLab repository is private, use GitHub.*
```bash
git clone https://gitlab.com/bluemoon7/transcription-suite.git
cd transcription-suite
```

### 3.2 Step 2: Run Setup Script

**Linux:**
```bash
cd build/user-setup
./setup.sh
```

**Windows (PowerShell):**
```powershell
cd build\user-setup
.\setup.ps1
```

The setup script will:
1. Check that Docker is installed and running
2. Create the config directory with all necessary files
3. Pull the Docker image from GitHub Container Registry

### 3.3 Step 3: Configure HuggingFace Token (Optional)

For speaker diarization, you need a HuggingFace token:

1. Create a free account at [huggingface.co](https://huggingface.co)
2. Go to Settings → Access Tokens → Create new token (Read permissions)
3. Accept the [PyAnnote model license](https://huggingface.co/pyannote/speaker-diarization-community-1)

**Linux:**
```bash
nano ~/.config/TranscriptionSuite/.env
# Add: HUGGINGFACE_TOKEN=hf_your_token_here
```

**Windows:**
```powershell
notepad "$env:USERPROFILE\Documents\TranscriptionSuite\.env"
# Add: HUGGINGFACE_TOKEN=hf_your_token_here
```

### 3.4 Step 4: Start the Server (Local Mode)

**Linux:**
```bash
cd ~/.config/TranscriptionSuite
./start-local.sh
```

**Windows:**
```powershell
cd "$env:USERPROFILE\Documents\TranscriptionSuite"
.\start-local.ps1
```

Access the web interface at **http://localhost:8000**

### 3.5 Stop the Server

**Linux:**
```bash
cd ~/.config/TranscriptionSuite
./stop.sh
```

**Windows:**
```powershell
cd "$env:USERPROFILE\Documents\TranscriptionSuite"
.\stop.ps1
```

---

## 4. Remote Access (Optional)

TranscriptionSuite uses a **layered security model** for remote access:

| Layer | Protection |
|-------|------------|
| **Tailscale Network** | Only devices on your Tailnet can reach the server |
| **TLS/HTTPS** | All traffic encrypted with Tailscale certificates |
| **Token Authentication** | Required for all API requests in remote mode |

### 4.1 Step 1: Set Up Tailscale

1. Install Tailscale: [tailscale.com/download](https://tailscale.com/download)
2. Authenticate: `tailscale up` (Linux) or via the app (Windows)
3. Go to [Tailscale Admin Console](https://login.tailscale.com/admin) → DNS tab
4. Enable **MagicDNS** and **HTTPS Certificates**

Your DNS settings should look like this:

![Tailscale DNS Settings](./build/assets/tailscale-dns-settings.png)

### 4.2 Step 2: Generate Certificates

```bash
# Generate certificate for your machine
sudo tailscale cert your-machine.your-tailnet.ts.net
```

Move the certificates to the standard location:

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

### 4.3 Step 3: Configure TLS Paths

Edit your config file to set the certificate paths:

**Linux:**
```bash
nano ~/.config/TranscriptionSuite/config.yaml
```

**Windows:**
```powershell
notepad "$env:USERPROFILE\Documents\TranscriptionSuite\config.yaml"
```

Update the `remote_server.tls` section:
```yaml
remote_server:
  tls:
    host_cert_path: "~/.config/Tailscale/my-machine.crt"
    host_key_path: "~/.config/Tailscale/my-machine.key"
```

### 4.4 Step 4: Start Server (Remote Mode)

**Linux:**
```bash
cd ~/.config/TranscriptionSuite
./start-remote.sh
```

**Windows:**
```powershell
cd "$env:USERPROFILE\Documents\TranscriptionSuite"
.\start-remote.ps1
```

### 4.5 Step 5: Save the Admin Token (First Run Only)

On first startup, an admin token is automatically generated. **Save this token!**

```bash
# Wait ~10 seconds for startup, then:
docker compose logs | grep "Admin Token"
```

Use this token to log in at `https://your-machine.your-tailnet.ts.net:8443`

---

## 5. Remote Access Without MagicDNS

If you cannot or prefer not to use Tailscale MagicDNS, you have alternative options.

### 5.1 Option 1: IP-Only Mode (Recommended)

Use Tailscale IPs directly with HTTP. WireGuard encrypts all traffic at the network layer.

**Server:** Start with `./start-local.sh` (HTTP on port 8000)

**Client:**
1. Find server's Tailscale IP: `tailscale ip -4`
2. Configure:
   - Host: `100.x.y.z` (Tailscale IP)
   - Port: `8000`
   - HTTPS: Off
   - Settings → Advanced TLS Options: Enable "Allow HTTP to remote hosts"

**Security:** WireGuard encrypts all Tailscale traffic. HTTP over Tailscale is secure for single-user setups.

### 5.2 Option 2: Self-Signed Certificates

For HTTPS without MagicDNS:

1. Generate certificates:
   ```bash
   openssl req -x509 -newkey rsa:4096 -keyout server.key -out server.crt \
       -days 365 -nodes -subj "/CN=100.x.y.z"
   ```

2. Configure server with certificates (see [README_DEV.md](README_DEV.md))

3. Configure client:
   - Host: `100.x.y.z`
   - Port: `8443`
   - HTTPS: On
   - Settings → Advanced TLS Options: Uncheck "Verify TLS certificates"

### 5.3 Why MagicDNS is Recommended

Tailscale HTTPS certificates require MagicDNS because:
- Certificates are issued for `.ts.net` hostnames, not IP addresses
- This is a Let's Encrypt/CA limitation, not Tailscale-specific

Enable MagicDNS in [Tailscale Admin Console](https://login.tailscale.com/admin/dns) for the best experience.

---

## 6. Dashboard

Download the Dashboard for your platform:

| Platform | Download | Notes |
|----------|----------|-------|
| **KDE Plasma** | `TranscriptionSuite-KDE-x86_64.AppImage` | Standalone, no dependencies |
| **GNOME** | `TranscriptionSuite-GNOME-x86_64.AppImage` | Requires system packages (see below) |
| **Windows** | `TranscriptionSuite.exe` | Standalone, no dependencies |

### 6.1 First-Time Setup

On first run, the Dashboard automatically performs initial setup:
1. Checks Docker availability
2. Creates the config directory with required files
3. Pulls the Docker image from GitHub Container Registry

This replaces the manual `setup.sh`/`setup.ps1` script execution for most users.

### 6.2 GNOME Dashboard Dependencies

The GNOME Dashboard uses a **dual-process architecture** because GTK3 (AppIndicator3 for the tray) and GTK4 (libadwaita for the Dashboard window) cannot coexist in the same Python process. The tray and Dashboard communicate via D-Bus.

You also need the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/) for the tray icon.

> **Note:** The tray will work without GTK4/libadwaita, but "Show App" will be unavailable.

**Ubuntu 24.04 (GNOME):**
```bash
sudo apt install python3 python3-gi gir1.2-appindicator3-0.1 python3-pyaudio \
    python3-numpy python3-aiohttp gir1.2-adw-1 gir1.2-gtk-4.0 gir1.2-gtksource-5
```

**Fedora (GNOME):**
```bash
sudo dnf install python3 python3-gobject gtk3 libappindicator-gtk3 python3-pyaudio \
    python3-numpy python3-aiohttp libadwaita gtk4 gtksourceview5
```

**Arch Linux (GNOME):**
```bash
sudo pacman -S --needed python python-gobject gtk3 libappindicator-gtk3 python-pyaudio \
    python-numpy python-aiohttp libadwaita gtk4 gtksourceview5
```

### 6.3 KDE Client Dependencies

The KDE client is a self-contained AppImage on Linux and a standalone executable on Windows. No additional system packages are required.

**Arch Linux (KDE Plasma) - from source only:**
```bash
sudo pacman -S --needed python python-pyqt6 python-pyaudio python-numpy python-aiohttp
```

**Fedora (KDE Plasma) - from source only:**
```bash
sudo dnf install python3 python3-qt6 python3-pyaudio python3-numpy python3-aiohttp
```

### 6.4 Usage

1. Run the AppImage or executable
2. The tray icon appears in your system tray
3. **Left-click** to start recording
4. **Middle-click** to stop and transcribe
5. Result is automatically copied to clipboard

### 6.5 Docker Server Control

The client includes a full Docker management GUI. Click the tray icon and select "Show App" to open the Dashboard window, which provides:

- **Server View**: Full Docker management including:
  - Container and image status with health indicators
  - Volume status with sizes and downloaded models list
  - 3-column management section (Container | Image | Volumes)
  - Server configuration with Settings button
- **Client View**: Start/stop client, configure settings
- **Help Menu**: Access built-in documentation (User Guide / Developer Guide)
- **About Dialog**: Application info and links to GitHub/GitLab
- Navigation bar with Home, Server, Client, Help, and About buttons (all with icons)

The tray menu also provides quick access:

| Menu Item | Action |
|-----------|--------|
| **Docker Server → Start Server (Local)** | Start in HTTP mode (port 8000) |
| **Docker Server → Start Server (Remote)** | Start in HTTPS mode (port 8443) |
| **Docker Server → Stop Server** | Stop the running server |

This eliminates the need to run scripts manually from the command line.

### 6.6 Tray Icon Colors

| Color | State |
|-------|-------|
| Grey | Disconnected |
| Green | Ready |
| Yellow | Recording |
| Blue | Uploading |
| Orange | Transcribing |
| Red | Error |

### 6.7 Client Configuration

On first connection, enter the server details:
- **Local mode**: Host `localhost`, Port `8000`, HTTPS off
- **Remote mode**: Host `your-machine.your-tailnet.ts.net`, Port `8443`, HTTPS on, Token from server logs

Settings are saved to:
- **Linux**: `~/.config/TranscriptionSuite/dashboard.yaml`
- **Windows**: `%APPDATA%\TranscriptionSuite\dashboard.yaml`

---

## 7. Web Interface

Access the web interface at your server's address:
- **Local**: http://localhost:8000
- **Remote**: https://your-machine.your-tailnet.ts.net:8443

**Features:**
- Calendar view of recordings
- Full-text search across all transcriptions
- Audio playback with click-to-seek timestamps
- AI chat about recordings (requires LM Studio)
- Import external audio files

---

## 8. Database & Backups

TranscriptionSuite automatically backs up the SQLite database on server startup:

- Backups are stored in the Docker volume (`/data/database/backups/`)
- A new backup is created if the latest is more than 1 hour old
- Up to 3 backups are kept (oldest automatically deleted)
- Uses SQLite's built-in backup API (safe with concurrent access)

**Configuration** (in `config.yaml`):
```yaml
backup:
    enabled: true        # Enable/disable automatic backups
    max_age_hours: 1     # Backup if latest is older than this
    max_backups: 3       # Number of backups to keep
```

**Manual Backup:**
```bash
# Stop the server first
docker compose down

# Copy the database file
docker run --rm -v transcription-suite-data:/data -v $(pwd):/backup \
    alpine cp /data/database/notebook.db /backup/notebook_backup.db

# Restart the server
docker compose up -d
```

---

## 9. Troubleshooting

### 9.1 Server Won't Start

Check Docker logs:
```bash
docker compose logs -f
```

Alternatively install `lazydocker`, it's an excellent cli tool to manage docker.
*(Then simply run it by running `lazydocker` in your terminal. Select your container on the left and you'll see its logs on the right.)*

### 9.2 GPU Not Detected

Verify NVIDIA Container Toolkit is installed:
```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04 nvidia-smi
```

### 9.3 GNOME Tray Icon Not Showing

Install the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/).

### 9.4 Connection Issues (Remote Mode)

1. Verify Tailscale is connected: `tailscale status`
2. Check certificate paths in `config.yaml`
3. Ensure port 8443 is used for HTTPS

**DNS Resolution Errors:**

If you see errors like `Name or service not known` for `.ts.net` hostnames:

- **Automatic fallback:** The client automatically tries to use Tailscale IP addresses when DNS fails. Check the logs for "Tailscale IP fallback" messages.
- **Check for DNS fight:** Run `tailscale status` and look for DNS warnings. If you see `/etc/resolv.conf overwritten`, your system's DNS isn't forwarding to Tailscale's MagicDNS.
- **Manual workaround:** Use the Tailscale IP directly: `--host 100.x.x.x` (find IPs with `tailscale status`)

See [README_DEV.md](README_DEV.md#tailscale-dns-resolution-issues) for detailed troubleshooting.

---

## 10. Security

TranscriptionSuite uses a layered security model (see [Security Model](README_DEV.md#security-model) in README_DEV.md):
- **Network isolation** via Tailscale VPN
- **TLS/HTTPS** encryption with certificate validation
- **Token-based authentication** for API access

The project undergoes continuous security analysis:
- **GitHub CodeQL** scans run automatically on every push and weekly
- **Security-extended queries** analyze Python and TypeScript code for vulnerabilities
- Results are monitored in the [Security](https://github.com/homelab-00/TranscriptionSuite/security) tab

---

## 11. License

MIT License — See [LICENSE](LICENSE).

## 12. Acknowledgments

- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [OpenAI Whisper](https://github.com/openai/whisper)
- [PyAnnote Audio](https://github.com/pyannote/pyannote-audio)
- [Tailscale](https://tailscale.com/)
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT)