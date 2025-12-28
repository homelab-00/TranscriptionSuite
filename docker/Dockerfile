# TranscriptionSuite Unified Server Dockerfile
# Multi-stage build for optimized image size
#
# Build:
#   docker build -t ghcr.io/homelab-00/transcriptionsuite-server:latest -f docker/Dockerfile .
#
# Run:
#   docker run -it --gpus all -v transcription-data:/data -p 8000:8000 ghcr.io/homelab-00/transcriptionsuite-server:latest
#
# =============================================================================
# Stage 1: Frontend Builder
# =============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /build

# Build unified frontend (contains Calendar, Search, Import, Record, and Admin views)
COPY server/frontend/package*.json ./frontend/
WORKDIR /build/frontend
RUN npm ci

COPY server/frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Python Builder (with build dependencies)
# =============================================================================
FROM ubuntu:22.04 AS python-builder

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install build dependencies (will be removed in final stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh

# Create app directory
WORKDIR /app

# Configure uv to use system Python and target venv location
ENV UV_PYTHON=python3.11
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Install Python dependencies from backend pyproject.toml
# Copy only dependency files first for better layer caching
COPY README.md ./
COPY server/backend/pyproject.toml ./server/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd server && \
    uv sync

# =============================================================================
# Stage 3: Python Runtime (minimal, without build dependencies)
# =============================================================================
FROM ubuntu:22.04 AS runtime

# GitHub Container Registry label
LABEL org.opencontainers.image.source=https://github.com/homelab-00/TranscriptionSuite

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install only runtime dependencies (no build-essential, no python-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser

# Create app directory
WORKDIR /app

# Configure Python environment
ENV UV_PYTHON=python3.11
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Copy built Python virtual environment from builder stage
COPY --from=python-builder /app/.venv /app/.venv

# Copy server application code
COPY server/backend/ ./server/
COPY docker/entrypoint.py ./docker/

# Copy built frontend to static serving location (unified UI)
COPY --from=frontend-builder /build/frontend/dist ./static/frontend

# Copy default configuration (users can override via mounted /user-config/config.yaml)
COPY server/config.yaml ./config.yaml

# Create data directories with correct permissions
# /user-config is for user-mounted config and logs (optional)
RUN mkdir -p /data/database /data/audio /data/logs /data/tokens /models /user-config && \
    chown -R appuser:appuser /data /app /models /user-config

# Environment variables
ENV DATA_DIR=/data
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV LOG_LEVEL=INFO
ENV HF_HOME=/models
# Prioritize PyTorch's bundled cuDNN over system cuDNN to avoid version mismatch
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.11/site-packages/torch/lib:$LD_LIBRARY_PATH

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Switch to non-root user
USER appuser

# Entrypoint with first-run setup support
# Use --setup for interactive configuration, or provide env vars
ENTRYPOINT ["python", "docker/entrypoint.py"]
CMD []
