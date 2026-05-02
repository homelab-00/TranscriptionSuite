# Vulkan-WSL2 sidecar image — whisper.cpp with Mesa's `dzn` Vulkan-on-D3D12 ICD
# added on top of the upstream `main-vulkan` image, so it can enumerate
# /dev/dxg on Windows + Docker Desktop with the WSL2 backend (GH-101 follow-up).
#
# The upstream image (ghcr.io/ggml-org/whisper.cpp:main-vulkan) is built
# FROM ubuntu:24.04 with `mesa-vulkan-drivers` from the stock Ubuntu archive.
# That package ships intel/intel_hasvk/lvp/radeon/virtio ICDs only — NOT dzn.
# Without dzn, the Vulkan loader on WSL2 either finds no devices or falls back
# to `llvmpipe` (CPU rasterizer), which would be silent CPU-bound transcription
# masquerading as GPU acceleration.
#
# The kisak/turtle PPA is the most widely-cited Ubuntu deb source that ships
# Mesa with `microsoft-experimental` enabled (i.e. with dzn). The PPA is a
# rolling release — we do NOT pin specific package versions here, so a fresh
# build always picks up the current PPA contents. If a PPA-side regression
# breaks the build, the post-install `RUN test -f .../dzn_icd.x86_64.json`
# below fails the build loudly so the maintainer notices immediately rather
# than shipping a silent CPU-fallback image. For deterministic builds,
# install with explicit `mesa-vulkan-drivers=<version>` constraints below.
#
# Build:
#   bash server/docker/build-vulkan-wsl2.sh
# (or directly:)
#   docker buildx build \
#       --tag transcriptionsuite/whisper-cpp-vulkan-wsl2:latest \
#       -f whisper-cpp-vulkan-wsl2.Dockerfile .
#
# This image is NOT published to GHCR for v1.3.5 — users build locally.
# Promote to GHCR after a real-world AMD/Intel WSL2 validator confirms
# /dev/dxg enumeration via dzn (i.e. vulkaninfo lists a discrete or
# integrated device, not just llvmpipe).

ARG UPSTREAM_IMAGE=ghcr.io/ggml-org/whisper.cpp:main-vulkan
FROM ${UPSTREAM_IMAGE}

# Avoid interactive tzdata prompts on apt install.
ARG DEBIAN_FRONTEND=noninteractive

# Reference build (informational, not a constraint): kisak/turtle PPA on
# 2026-05-02 shipped Mesa 25.x with microsoft-experimental enabled. If a
# future apt-get update introduces a regression, pin the relevant package
# versions explicitly via `=<version>` after the package name.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        software-properties-common \
        ca-certificates \
        gpg \
        gpg-agent; \
    add-apt-repository -y ppa:kisak/turtle; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        mesa-vulkan-drivers \
        libgl1 \
        libglx0 \
        libegl1 \
        libgles2 \
        libdrm2; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Sanity: confirm the dzn ICD manifest is now present. If this fails, the
# kisak PPA shape changed and the image will not enumerate /dev/dxg correctly
# at runtime — fail the build loudly so the maintainer notices immediately.
RUN test -f /usr/share/vulkan/icd.d/dzn_icd.x86_64.json \
    || (echo "ERROR: dzn ICD manifest missing after PPA install — Mesa build does not include dzn. Aborting image build." >&2 && exit 1)

# Default env hints — overridden by docker-compose.vulkan-wsl2.yml at runtime.
ENV LD_LIBRARY_PATH=/usr/lib/wsl/lib \
    VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/dzn_icd.x86_64.json
