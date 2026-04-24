# TranscriptionSuite — Deployment Guide

> Generated: 2026-04-05

## Deployment Architecture

TranscriptionSuite deploys as two components:
1. **Dashboard** — Electron desktop app installed on the user's machine
2. **Server** — Docker container running on the same machine or a remote server

## Docker Compose Variants

The server uses a **layered compose** strategy. The dashboard auto-selects the correct combination:

### Base (always included)
- `docker-compose.yml` — Service definition, volumes, environment variables

### Platform Overlays (pick one)
| File | Platform | Networking |
|------|----------|-----------|
| `docker-compose.linux-host.yml` | Linux | Host networking (direct localhost access) |
| `docker-compose.desktop-vm.yml` | macOS / Windows | Bridge + port mapping (9786:9786) |

### GPU Overlays (pick one, optional)
| File | GPU Type | Mechanism |
|------|----------|-----------|
| `docker-compose.gpu.yml` | NVIDIA (legacy) | `deploy.resources.reservations.devices` with nvidia driver |
| `docker-compose.gpu-cdi.yml` | NVIDIA (CDI) | CDI device passthrough (`nvidia.com/gpu=all`) |
| `docker-compose.vulkan.yml` | AMD / Intel | whisper.cpp sidecar with `/dev/dri` Vulkan access |
| `podman-compose.gpu.yml` | NVIDIA (Podman) | Podman-specific GPU passthrough |

### Common Combinations
```bash
# Linux + NVIDIA GPU (most common)
docker compose -f docker-compose.yml \
  -f docker-compose.linux-host.yml \
  -f docker-compose.gpu.yml up -d

# macOS / Windows CPU
docker compose -f docker-compose.yml \
  -f docker-compose.desktop-vm.yml up -d

# Linux + AMD/Intel GPU (Vulkan)
docker compose -f docker-compose.yml \
  -f docker-compose.linux-host.yml \
  -f docker-compose.vulkan.yml up -d
```

## Docker Volumes

| Volume Name | Mount Point | Purpose |
|-------------|------------|---------|
| `transcriptionsuite-data` | `/data` | Database, audio files, tokens, logs |
| `transcriptionsuite-models` | `/models` | HuggingFace model cache (~2-30GB) |
| `transcriptionsuite-runtime` | `/runtime` | Python venv, bootstrap state, uv cache |

**Bind mounts** (optional):
| Source | Target | Purpose |
|--------|--------|---------|
| `USER_CONFIG_DIR` | `/user-config` | Custom config.yaml and logs |
| `TLS_CERT_PATH` | `/certs/cert.crt` | TLS certificate (read-only) |
| `TLS_KEY_PATH` | `/certs/cert.key` | TLS private key (read-only) |
| `STARTUP_EVENTS_DIR` | `/startup-events` | Bootstrap progress for Electron |

## Bootstrap System

On first container start, the server installs Python dependencies into `/runtime/.venv`:

1. **Fingerprint check** — Compare schema version, Python ABI, arch, GPU driver, extras, uv.lock
2. **Cache hit** — Skip install if fingerprint matches
3. **Cache miss** — Run `uv sync --frozen` with appropriate extras
4. **Status file** — Write `bootstrap-status.json` with installed features
5. **Startup events** — Emit progress to JSONL file for dashboard

**Extras selected by model type:**
- Whisper model → `--extra whisper`
- NeMo model → `--extra nemo` (requires `INSTALL_NEMO=true`)
- VibeVoice model → `--extra vibevoice_asr` (requires `INSTALL_VIBEVOICE_ASR=true`)

**Timeout:** 30 minutes default (`BOOTSTRAP_TIMEOUT_SECONDS=1800`)

## TLS / Remote Access

### Tailscale Setup
```bash
# 1. Generate certificates
tailscale cert your-machine.tailnet-name.ts.net

# 2. Start with TLS
TLS_ENABLED=true \
TLS_CERT_PATH=~/.config/Tailscale/your-machine.crt \
TLS_KEY_PATH=~/.config/Tailscale/your-machine.key \
docker compose -f docker-compose.yml \
  -f docker-compose.linux-host.yml \
  -f docker-compose.gpu.yml up -d
```

When TLS is enabled:
- All routes require Bearer token authentication (except `/health`, `/api/auth/login`)
- Admin token generated on first run (shown in server logs)
- Dashboard auto-detects token from Docker log output

## GPU Requirements

### NVIDIA CUDA
- CUDA 12.9+ (explicit PyPI index override for PyTorch)
- nvidia-container-toolkit or nvidia-container-runtime
- 6-16GB VRAM depending on model
- CDI mode available for newer setups
- **Modern GPUs only** — the default image ships PyTorch cu129 wheels, which
  support compute capability `sm_70..sm_120` (Volta and newer: RTX 20/30/40/50,
  Tesla V100/A100/H100, data-centre L4/L40, etc.). Pascal (GTX 10-series) and
  Maxwell (GTX 9-series, Tesla M40) are **not** supported by the default image —
  see [Legacy-GPU image variant](#legacy-gpu-image-variant-issue-83) below.

### Legacy-GPU image variant (Issue #83)

Users with Pascal (`sm_6x`) or Maxwell (`sm_5x`) cards — e.g. **GTX 1070, GTX
1080, Tesla P4/P40/P100, Tesla M40** — need the `-legacy` image, which is
built against PyTorch cu126 wheels (still ships `sm_50..sm_90`). The cu129
wheels rebuilt with these cards were dropped upstream; that's why Issue #60's
compute-type auto-correction doesn't help — PyTorch rejects the GPU outright
before the backend can downgrade `float16` to `int8`.

**Enable it via the dashboard:**
Server settings → Runtime = **GPU (CUDA)** → flip the **"Use legacy-GPU image
(GTX 10-series / 900-series and older)"** toggle (only visible when the CUDA
runtime is selected). The dashboard switches to the
`ghcr.io/homelab-00/transcriptionsuite-server-legacy` repo for the remainder
of the session; confirm the restart prompt to wipe the runtime volume so the
next bootstrap re-syncs wheels from the cu126 index.

**Build & push it manually:**
```bash
# From the repo root — build locally with the cu126 build-arg, then push to the
# -legacy GHCR repo. The default `docker compose build` is unaffected.
./build/docker-build-push.sh --variant legacy --build v1.3.4
```
`--variant legacy` flips both the build-arg (`PYTORCH_VARIANT=cu126`) and the
push target (`…/transcriptionsuite-server-legacy`). `latest` is auto-tagged
only within its own repo, never across the two.

**Post-push smoke check (mandatory on first push of a new package).**
GHCR defaults first-push visibility to `Private`, which produces a 403 on
anonymous pulls and misroutes in the dashboard. The script now prints a
reminder on every push; on the **first** push of a newly created GHCR package
(e.g. the initial `-legacy` publish for v1.3.3), flip the package to Public
at `https://github.com/users/homelab-00/packages/container/<pkg>/settings`
and then run the anonymous-pull smoke check from a shell with no GHCR creds:

```bash
docker logout ghcr.io
docker pull ghcr.io/homelab-00/transcriptionsuite-server-legacy:v1.3.4
```

If the pull succeeds, the image is externally reachable. If it 403s, the
package is still Private — fix visibility before announcing the release.
This single step catches both the GHCR private-default failure mode *and*
the "forgot to push one of the tags" variant.

**Caveats:**
- First-run bootstrap takes longer than the default variant — the legacy path
  runs `uv sync` without `--frozen` because `uv.lock` pins wheel hashes to the
  cu129 index. It does a fresh resolve + download against cu126.
- Reproducibility guarantees are weaker for this variant only.
- Not available in `release.yml` — the legacy image is published manually by
  the maintainer (consistent with the existing Docker publishing flow).

**Manual `compose build`: `IMAGE_REPO` and `PYTORCH_VARIANT` must be paired.**
`server/docker/docker-compose.yml` reads both through env vars with independent
defaults (`IMAGE_REPO=…-server`, `PYTORCH_VARIANT=cu129`). Setting only one
locally produces a misleading image — the tag claims one variant while the
installed wheels are the other. The dashboard never calls `compose build` (it
always `docker pull`s pre-built images), so this footgun only affects manual
CLI workflows. Rule of thumb:

```bash
# Default (modern GPUs) — both defaults apply; nothing to export.
docker compose build

# Legacy (Pascal/Maxwell) — export BOTH, never one in isolation:
IMAGE_REPO=ghcr.io/homelab-00/transcriptionsuite-server-legacy \
PYTORCH_VARIANT=cu126 \
docker compose build
```

`server/docker/start-common.sh` inspects the resolved image on startup and
prints a warning if the baked `PYTORCH_VARIANT` does not match the repo
implied by `IMAGE_REPO`, so a mismatched build is surfaced before you spend
an hour debugging a cryptic CUDA error on first transcription.

**Grandfathering existing users through GH-83 (Blind #10).** The runtime
bootstrap fingerprint absorbed `pytorch_variant` in GH-83. To avoid forcing
every existing cu129 user to pay a full `uv sync` rebuild on the upgrade,
`bootstrap_runtime.py` treats a pre-GH-83 marker (no `pytorch_variant` field)
as implicitly cu129 and recomputes the legacy fingerprint form; if it
matches, the marker is rewritten in place and the next boot takes the fast
hash-match-skip path. Users flipping to cu126 still rebuild — only the
non-flipping cu129 path is zero-cost.

### AMD/Intel Vulkan
- Vulkan-capable GPU with `/dev/dri` access
- Uses whisper.cpp sidecar (`ghcr.io/ggml-org/whisper.cpp:main-vulkan`)
- Quantized GGUF models only (lower VRAM requirement)

### Apple Silicon (Metal)
- MLX framework (no Docker needed)
- Setup via `build/setup-macos-metal.sh`
- Creates self-contained `.app` with bundled Python venv

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SERVER_PORT` | 9786 | HTTP/HTTPS port |
| `LOG_LEVEL` | INFO | Logging verbosity |
| `HUGGINGFACE_TOKEN` | (empty) | For gated models (PyAnnote diarization) |
| `MAIN_TRANSCRIBER_MODEL` | (empty) | Override default STT model |
| `LIVE_TRANSCRIBER_MODEL` | (empty) | Override live mode model |
| `INSTALL_WHISPER` | false | Install faster-whisper extras |
| `INSTALL_NEMO` | false | Install NeMo toolkit |
| `INSTALL_VIBEVOICE_ASR` | false | Install VibeVoice backend |
| `TLS_ENABLED` | false | Enable HTTPS + auth |
| `LM_STUDIO_URL` | http://127.0.0.1:1234 | LM Studio API endpoint |

## Health Monitoring

- **Liveness:** `GET /health` (no auth, always available)
- **Readiness:** `GET /ready` (200 when models loaded, 503 when loading)
- **Status:** `GET /api/status` (detailed: GPU, model, features, config)
- **Docker healthcheck:** curl to `/health` every 30s, 600s start period

## Security

- Non-root container user (`appuser`, UID 10000)
- Token-based auth with SHA-256 hashing (TLS mode)
- Origin validation middleware (CORS policy)
- Stop grace period: 130s (matches 120s drain timeout)
- GPG-signed release artifacts (optional)

## CI/CD Release Pipeline

Triggered by `v*` tag push:
1. **build-linux** — AppImage + GPG signature
2. **build-windows** — NSIS installer + GPG signature (3x retry)
3. **build-macos** — DMG + ZIP + GPG signatures
4. **create-release** — Draft GitHub Release with all artifacts
