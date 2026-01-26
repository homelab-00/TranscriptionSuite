# TranscriptionSuite Unified Server Dockerfile
# Multi-stage build for optimized image size
#
# Build:
#   docker build -t ghcr.io/homelab-00/transcriptionsuite-server:latest -f server/docker/Dockerfile .
#
# Run:
#   docker run -it --gpus all -v transcription-data:/data -p 8000:8000 ghcr.io/homelab-00/transcriptionsuite-server:latest
#
# =============================================================================
# Stage 1: Python Builder (with build dependencies)
# =============================================================================
FROM ubuntu:24.04 AS python-builder

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install build dependencies (will be removed in final stage)
# Add deadsnakes PPA for Python 3.13
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    python3.13 \
    python3.13-venv \
    python3.13-dev \
    python3-pip \
    curl \
    git \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh

# Create app directory
WORKDIR /app

# Configure uv to use system Python and target venv location
ENV UV_PYTHON=python3.13
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Install Python dependencies from backend pyproject.toml
# Copy only dependency files first for better layer caching
COPY README.md ./
COPY server/backend/pyproject.toml ./server/
COPY server/backend/uv.lock ./server/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd server && \
    uv sync

# =============================================================================
# Stage 2: Python Runtime (minimal, without build dependencies)
# =============================================================================
FROM ubuntu:24.04 AS runtime

# GitHub Container Registry label
LABEL org.opencontainers.image.source=https://github.com/homelab-00/TranscriptionSuite

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install only runtime dependencies (no build-essential, no python-dev)
# gosu is used to drop privileges from root to appuser after TLS cert setup
# Add deadsnakes PPA for Python 3.13
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.13 \
    python3.13-venv \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libavdevice-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    libsndfile1 \
    libportaudio2 \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
# Don't specify UID to avoid conflicts - let the system assign one
RUN useradd -m -s /bin/bash appuser

# Create app directory
WORKDIR /app

# Configure Python environment
ENV UV_PYTHON=python3.13
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Copy built Python virtual environment from builder stage
COPY --from=python-builder /app/.venv /app/.venv

# Copy server application code
COPY server/backend/ ./server/
COPY server/docker/entrypoint.py ./docker/
COPY server/docker/docker-entrypoint.sh ./docker/
RUN chmod +x ./docker/docker-entrypoint.sh

# Copy default configuration (users can override via mounted /user-config/config.yaml)
COPY server/config.yaml ./config.yaml

# Create data directories with correct permissions
# /user-config is for user-mounted config and logs (optional)
# /certs is for bind-mounted TLS certificates (source, read-only)
RUN mkdir -p /data/database /data/audio /data/logs /data/tokens /data/certs /models /user-config /certs && \
    chown -R appuser:appuser /data /app /models /user-config

# Environment variables
ENV DATA_DIR=/data
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV LOG_LEVEL=INFO
ENV HF_HOME=/models
# Prioritize PyTorch's bundled cuDNN over system cuDNN to avoid version mismatch
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.13/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.13/site-packages/torch/lib:$LD_LIBRARY_PATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# NOTE: We don't use USER directive here because the shell entrypoint needs
# to run as root initially to copy TLS certificates with proper permissions.
# The docker-entrypoint.sh script uses su-exec to drop to appuser before
# running the Python application.

# Shell entrypoint handles TLS cert permissions then drops to appuser
ENTRYPOINT ["./docker/docker-entrypoint.sh"]
CMD []
