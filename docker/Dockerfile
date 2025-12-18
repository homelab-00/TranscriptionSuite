# TranscriptionSuite Unified Server Dockerfile
# Multi-stage build for optimized image size
#
# Build: docker build -t transcriptionsuite/server -f docker/Dockerfile .
# Run:   docker run -it --gpus all -v transcription-data:/data -p 8000:8000 transcriptionsuite/server

# =============================================================================
# Stage 1: Frontend Builder
# =============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /build

# Build Audio Notebook frontend
COPY native_src/AUDIO_NOTEBOOK/package*.json ./audio_notebook/
WORKDIR /build/audio_notebook
RUN npm ci --omit=dev

COPY native_src/AUDIO_NOTEBOOK/ ./
RUN npm run build

# Build Remote Server frontend
WORKDIR /build
COPY native_src/REMOTE_SERVER_WEB/package*.json ./remote_server/
WORKDIR /build/remote_server
RUN npm ci --omit=dev

COPY native_src/REMOTE_SERVER_WEB/ ./
RUN npm run build

# =============================================================================
# Stage 2: Python Runtime
# =============================================================================
FROM nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04 AS runtime

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser

# Create app directory
WORKDIR /app

# Create virtual environment
RUN python3.11 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Install Python dependencies from server/pyproject.toml
# Copy only dependency files first for better layer caching
COPY server/pyproject.toml ./server/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir ./server[diarization]

# Copy server application code
COPY server/ ./server/
COPY docker/entrypoint.py ./docker/

# Copy built frontends to static serving location
COPY --from=frontend-builder /build/audio_notebook/dist ./static/audio_notebook
COPY --from=frontend-builder /build/remote_server/dist ./static/remote_ui

# Copy configuration template
COPY config/server.yaml.example ./config/server.yaml.example

# Create data directories with correct permissions
RUN mkdir -p /data/database /data/audio /data/logs /data/certs /data/config && \
    chown -R appuser:appuser /data /app

# Environment variables
ENV DATA_DIR=/data
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV LOG_LEVEL=INFO

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
