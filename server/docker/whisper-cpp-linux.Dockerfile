# Custom whisper.cpp Vulkan build for pre-Haswell CPUs (AVX + F16C; no AVX2/FMA).
#
# The stock ghcr.io/ggml-org/whisper.cpp:main-vulkan image ships a libggml-cpu
# compiled with an AVX2/FMA baseline. On CPUs without AVX2/FMA (e.g. Intel Ivy
# Bridge — i5-3570K) whisper-server enumerates Vulkan fine, then dies with SIGILL
# ("trap invalid opcode in libggml-cpu.so", container exit 132) because parts of
# the pipeline always run on the CPU backend. This image rebuilds whisper-server
# with GGML_NATIVE=OFF and an explicit AVX+F16C-only instruction set so the CPU
# backend runs on older x86, while the RX 580 (Mesa RADV) does the heavy lifting
# via the Vulkan backend.
#
# Adapted from whisper.cpp (https://github.com/ggml-org/whisper.cpp) — Vulkan
# server build with a lowered CPU instruction baseline.
#
# This is the sidecar image the app pulls for the Linux "vulkan" profile — both
# docker-compose.vulkan.yml (image:) and dockerManager.ts (VULKAN_SIDECAR_IMAGE)
# reference it by the GHCR name below, so it fully replaces the upstream
# main-vulkan image for all Linux Vulkan users.
#
# Build + push to GHCR (requires `write:packages`; make the package Public
# afterwards so end users can pull without auth):
#
#   gh auth token | docker login ghcr.io -u homelab-00 --password-stdin
#   cd server/docker
#   docker build -f whisper-cpp-linux.Dockerfile \
#     -t ghcr.io/homelab-00/whisper-cpp-linux:latest .
#   docker push ghcr.io/homelab-00/whisper-cpp-linux
# Pin whisper.cpp to a specific release instead of master:
#   docker build --build-arg WHISPER_CPP_REF=v1.7.4 -f ...

ARG WHISPER_CPP_REF=master

# ---------- build stage ----------
FROM ubuntu:24.04 AS build
ARG WHISPER_CPP_REF
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates cmake build-essential \
        libvulkan-dev glslc spirv-headers spirv-tools glslang-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch "${WHISPER_CPP_REF}" \
        https://github.com/ggml-org/whisper.cpp.git .

# GGML_NATIVE=OFF stops ggml adding -march=native; we then turn on ONLY the
# extensions Ivy Bridge supports (SSE4.2 + AVX + F16C) and explicitly disable
# everything Haswell-and-later: AVX2, FMA, BMI2, AVX512. NOTE: GGML_BMI2
# defaults ON and BMI2 is Haswell+ — leaving it on reintroduces the same SIGILL.
# BUILD_SHARED_LIBS=OFF folds libggml*/libwhisper into the single whisper-server
# binary so the runtime stage needs no .so copying.
RUN cmake -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF \
        -DGGML_VULKAN=ON \
        -DGGML_NATIVE=OFF \
        -DGGML_SSE42=ON \
        -DGGML_AVX=ON \
        -DGGML_F16C=ON \
        -DGGML_AVX2=OFF \
        -DGGML_FMA=OFF \
        -DGGML_BMI2=OFF \
        -DGGML_AVX512=OFF \
        -DWHISPER_BUILD_EXAMPLES=ON \
        -DWHISPER_BUILD_TESTS=OFF \
        -DWHISPER_CURL=OFF \
    && cmake --build build --config Release -j"$(nproc)" --target whisper-server

# ---------- runtime stage ----------
FROM ubuntu:24.04 AS runtime
# Links the published GHCR package to the repo (Packages tab) and documents the
# no-AVX2 CPU baseline. org.opencontainers.image.source is what GHCR reads to
# associate the package with the repository automatically.
LABEL org.opencontainers.image.source="https://github.com/homelab-00/TranscriptionSuite" \
      org.opencontainers.image.description="whisper.cpp Vulkan sidecar rebuilt with an AVX+F16C CPU baseline (no AVX2/FMA) for pre-Haswell CPUs" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update && apt-get install -y --no-install-recommends \
        libvulkan1 mesa-vulkan-drivers \
        libgomp1 curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/build/bin/whisper-server /usr/local/bin/whisper-server

# Run as root, matching the upstream whisper.cpp image. With --convert (set in
# docker-compose.vulkan.yml's command), whisper-server writes a temp WAV to its
# CWD and shells out to ffmpeg to read it back, so the CWD must be writable —
# otherwise ffmpeg fails with "No such file or directory" -> HTTP 500 on
# /inference. The model volume is mounted read-only and world-readable, so root
# reads it fine without any uid matching. /tmp is a writable CWD for the temp WAV.
WORKDIR /tmp

# docker-compose.vulkan.yml supplies the `command:` (model-wait loop + exec
# whisper-server), so no ENTRYPOINT/CMD is needed here beyond a shell.
ENTRYPOINT ["/bin/sh", "-c"]
