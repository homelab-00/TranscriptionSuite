#!/usr/bin/env bash
# Build the Vulkan-WSL2 sidecar image locally (GH-101 follow-up).
#
# Tags: transcriptionsuite/whisper-cpp-vulkan-wsl2:latest
#
# This image is the experimental opt-in counterpart to the upstream
# ghcr.io/ggml-org/whisper.cpp:main-vulkan image, with Mesa's `dzn`
# Vulkan-on-D3D12 ICD added so it can enumerate /dev/dxg on Windows +
# Docker Desktop with the WSL2 backend.
#
# It is NOT published to GHCR for v1.3.5 — every user who wants to try the
# Vulkan-WSL2 runtime profile builds it locally with this script. After a
# real-world AMD/Intel WSL2 validator confirms /dev/dxg enumeration via
# vulkaninfo (i.e. discrete/integrated GPU listed, not just llvmpipe), we
# may promote to GHCR in a future release.
#
# Usage (on any host with docker buildx):
#   bash server/docker/build-vulkan-wsl2.sh
#
# Pass --no-cache to force a clean rebuild (useful when the kisak PPA shape
# changes). All other arguments are forwarded to `docker buildx build`.
#
# Requires:
#   * docker (or podman with `alias docker=podman`) with buildx
#   * Internet access to pull the upstream image and the kisak PPA

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
DOCKERFILE="${SCRIPT_DIR}/whisper-cpp-vulkan-wsl2.Dockerfile"
IMAGE_TAG="${IMAGE_TAG:-transcriptionsuite/whisper-cpp-vulkan-wsl2:latest}"

if [ ! -f "${DOCKERFILE}" ]; then
    echo "ERROR: Dockerfile not found at ${DOCKERFILE}" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker CLI not found in PATH. Install Docker Desktop or Docker Engine, then retry." >&2
    exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
    echo "ERROR: docker buildx is not available. Update Docker to a recent version (>= 20.10) and retry." >&2
    exit 1
fi

echo "[build-vulkan-wsl2] Building ${IMAGE_TAG} from ${DOCKERFILE}..."

# Forward all extra arguments (e.g. --no-cache, --progress=plain) preserving
# whitespace inside individual args. "$@" — not $@ — is the correct splat.
docker buildx build \
    --load \
    --tag "${IMAGE_TAG}" \
    -f "${DOCKERFILE}" \
    "${SCRIPT_DIR}" \
    "$@"

echo "[build-vulkan-wsl2] Done. Verify with: docker images | grep whisper-cpp-vulkan-wsl2"
echo "[build-vulkan-wsl2] To use: open the dashboard, switch to 'GPU (Vulkan WSL2 — experimental)', and Start Server."
