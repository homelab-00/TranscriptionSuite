# =============================================================================
# TranscriptionSuite Container
# Multi-stage build: Frontend assets + Python runtime with CUDA
# =============================================================================

# =============================================================================
# Stage 1: Build Frontend Assets
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Build Audio Notebook frontend
COPY AUDIO_NOTEBOOK/package*.json ./audio-notebook/
RUN cd audio-notebook && npm ci --silent

COPY AUDIO_NOTEBOOK/ ./audio-notebook/
RUN cd audio-notebook && npm run build

# Build Remote Server frontend
COPY REMOTE_SERVER/web/package*.json ./remote-server/
RUN cd remote-server && npm ci --silent

COPY REMOTE_SERVER/web/ ./remote-server/
RUN cd remote-server && npm run build

# =============================================================================
# Stage 2: Python Runtime with CUDA
# =============================================================================
FROM nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04 AS runtime

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    build-essential \
    ffmpeg \
    libsndfile1 \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Make python3.11 the default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install uv package manager
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy Python project files for dependency installation
COPY pyproject.toml uv.lock ./

# Create virtual environment and install dependencies
RUN uv venv --python 3.11 /app/.venv \
    && . /app/.venv/bin/activate \
    && uv sync --no-dev --frozen

# Copy application source code
COPY MAIN/ ./MAIN/
COPY DIARIZATION/ ./DIARIZATION/
COPY REMOTE_SERVER/*.py ./REMOTE_SERVER/
COPY REMOTE_SERVER/data/.gitkeep ./REMOTE_SERVER/data/
COPY AUDIO_NOTEBOOK/backend/ ./AUDIO_NOTEBOOK/backend/
COPY DOCKER/ ./DOCKER/
COPY config.yaml ./

# Copy built frontends from builder stage
COPY --from=frontend-builder /build/audio-notebook/dist ./AUDIO_NOTEBOOK/dist/
COPY --from=frontend-builder /build/remote-server/dist ./REMOTE_SERVER/web/dist/

# Create data directories
RUN mkdir -p /data/database /data/audio /data/certs /data/tokens

# Environment configuration
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose ports
# 8000: Audio Notebook (HTTP)
# 8443: Remote Server (HTTPS/WSS)
EXPOSE 8000 8443

# Persistent storage volume
VOLUME ["/data"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the container entrypoint
CMD ["python", "DOCKER/entrypoint.py"]
