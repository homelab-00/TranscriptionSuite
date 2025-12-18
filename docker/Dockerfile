# TranscriptionSuite Unified Server Dockerfile
# Multi-stage build for optimized image size

# =============================================================================
# Stage 1: Frontend Builder
# =============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /build

# Build Audio Notebook frontend
COPY AUDIO_NOTEBOOK/package*.json ./audio_notebook/
WORKDIR /build/audio_notebook
RUN npm ci --omit=dev

COPY AUDIO_NOTEBOOK/ ./
RUN npm run build

# Build Remote Server frontend (for backward compatibility)
WORKDIR /build
COPY REMOTE_SERVER/web/package*.json ./remote_server/
WORKDIR /build/remote_server
RUN npm ci --omit=dev

COPY REMOTE_SERVER/web/ ./
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
    python3-pip \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create virtual environment
RUN python3.11 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir uvicorn[standard]

# Copy application source
COPY server/ ./server/
COPY docker/ ./docker/
COPY config.yaml ./

# Copy legacy modules (for backward compatibility during migration)
COPY MAIN/ ./MAIN/
COPY DIARIZATION/ ./DIARIZATION/
COPY REMOTE_SERVER/ ./REMOTE_SERVER/
COPY AUDIO_NOTEBOOK/backend/ ./AUDIO_NOTEBOOK/backend/

# Copy built frontends
COPY --from=frontend-builder /build/audio_notebook/dist ./AUDIO_NOTEBOOK/dist
COPY --from=frontend-builder /build/remote_server/dist ./REMOTE_SERVER/web/dist

# Create data directories
RUN mkdir -p /data/database /data/audio /data/logs /data/certs /data/tokens

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

# Run the server
CMD ["python", "docker/entrypoint.py"]
