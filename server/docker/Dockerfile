# TranscriptionSuite Unified Server Dockerfile
#
# This image keeps application source and runtime bootstrap tooling.
# Python dependencies are installed at first container startup into /runtime/.venv.

FROM ubuntu:24.04 AS runtime

# OCI standard labels for container metadata
LABEL org.opencontainers.image.title="TranscriptionSuite Server"
LABEL org.opencontainers.image.description="Self contained server for TranscriptionSuite"
LABEL org.opencontainers.image.authors="homelab-00"
LABEL org.opencontainers.image.vendor="homelab-00"
LABEL org.opencontainers.image.source="https://github.com/homelab-00/TranscriptionSuite"
LABEL org.opencontainers.image.url="https://github.com/homelab-00/TranscriptionSuite"
LABEL org.opencontainers.image.documentation="https://github.com/homelab-00/TranscriptionSuite/blob/main/README.md"
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"

# Global environment
ENV DEBIAN_FRONTEND="noninteractive"
ENV PYTHONUNBUFFERED="1"
ENV PYTHONDONTWRITEBYTECODE="1"
ENV UV_PYTHON="3.13"
ENV BOOTSTRAP_RUNTIME_DIR="/runtime"
ENV BOOTSTRAP_STATUS_FILE="/runtime/bootstrap-status.json"
ENV BOOTSTRAP_TIMEOUT_SECONDS="1800"
ENV BOOTSTRAP_REQUIRE_HF_TOKEN="false"
ENV HF_HOME="/models"

# Install runtime + bootstrap build prerequisites.
# Some Python packages still need local compilation on first bootstrap.
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    python3.13 \
    python3.13-venv \
    python3.13-dev \
    ffmpeg \
    libsndfile1 \
    libportaudio2 \
    portaudio19-dev \
    curl \
    git \
    gosu \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh

# Create non-root user for security with pinned UID/GID
RUN groupadd -g 10000 appuser && \
    useradd -u 10000 -g 10000 -m -s /bin/bash appuser

# Create app directory
WORKDIR /app

# Copy server application code and bootstrap tooling.
# Files are owned by appuser to avoid expensive recursive chown layers.
COPY --chown=appuser:appuser server/backend/ ./server/
COPY --chown=appuser:appuser server/docker/entrypoint.py ./docker/
COPY --chown=appuser:appuser server/docker/bootstrap_runtime.py ./docker/
COPY server/docker/docker-entrypoint.sh ./docker/
RUN chmod 700 ./docker/docker-entrypoint.sh

# Copy default configuration (users can override via mounted /user-config/config.yaml)
COPY server/config.yaml ./config.yaml

# Create data directories with correct permissions
# /runtime is for first-run dependency bootstrap.
RUN mkdir -p /data/database /data/audio /data/logs /data/tokens /data/certs /models /user-config /certs /runtime && \
    chown -R appuser:appuser /data /models /user-config /runtime

# Environment variables
ENV DATA_DIR="/data"
ENV SERVER_HOST="0.0.0.0"
ENV SERVER_PORT="8000"
ENV LOG_LEVEL="INFO"
# Prioritize PyTorch bundled libraries from runtime venv.
ENV LD_LIBRARY_PATH="/runtime/.venv/lib/python3.13/site-packages/nvidia/cudnn/lib:/runtime/.venv/lib/python3.13/site-packages/torch/lib:$LD_LIBRARY_PATH"

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
