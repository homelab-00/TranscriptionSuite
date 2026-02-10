#!/bin/bash
# Docker entrypoint script for TranscriptionSuite.
#
# This script runs as root to:
# 1) handle TLS certificate permissions,
# 2) bootstrap runtime dependencies into /runtime/.venv,
# 3) drop privileges to appuser and launch the Python server.

set -e

# Function to log with timestamp
log() {
    echo "[entrypoint.sh] $1"
}

# Handle TLS certificates if TLS is enabled
if [ "${TLS_ENABLED:-false}" = "true" ]; then
    log "TLS enabled - preparing certificates..."
    
    CERT_SRC="${TLS_CERT_FILE:-/certs/cert.crt}"
    KEY_SRC="${TLS_KEY_FILE:-/certs/cert.key}"
    CERT_DST="/data/certs/server.crt"
    KEY_DST="/data/certs/server.key"
    
    # Create certs directory if it doesn't exist
    mkdir -p /data/certs
    
    # Check if source files exist
    if [ ! -f "$CERT_SRC" ]; then
        log "ERROR: TLS certificate not found at $CERT_SRC"
        exit 1
    fi
    if [ ! -f "$KEY_SRC" ]; then
        log "ERROR: TLS key not found at $KEY_SRC"
        exit 1
    fi
    
    # Copy certificates to data directory (running as root, so we can read them)
    log "Copying certificate from $CERT_SRC to $CERT_DST"
    cp "$CERT_SRC" "$CERT_DST"
    chmod 644 "$CERT_DST"
    
    log "Copying key from $KEY_SRC to $KEY_DST"
    cp "$KEY_SRC" "$KEY_DST"
    chmod 600 "$KEY_DST"
    
    # Change ownership to appuser
    chown appuser:appuser "$CERT_DST" "$KEY_DST"
    
    # Update environment variables to point to the copied files
    export TLS_CERT_FILE="$CERT_DST"
    export TLS_KEY_FILE="$KEY_DST"
    
    log "TLS certificates prepared successfully"
fi

# Ensure runtime directories are writable by appuser.
# Do NOT chown /user-config because it is typically a host bind mount
# and changing ownership here can break host-side dashboard permissions.
mkdir -p /data /models /user-config /runtime /runtime-cache
chown -R appuser:appuser /data /models /runtime /runtime-cache

# Bootstrap runtime dependencies and feature status.
log "Bootstrapping runtime environment..."
BOOTSTRAP_START_NS="$(date +%s%N)"
gosu appuser /usr/bin/python3.13 docker/bootstrap_runtime.py
BOOTSTRAP_END_NS="$(date +%s%N)"
BOOTSTRAP_ELAPSED_MS="$(( (BOOTSTRAP_END_NS - BOOTSTRAP_START_NS) / 1000000 ))"
BOOTSTRAP_ELAPSED_S="$(( BOOTSTRAP_ELAPSED_MS / 1000 ))"
BOOTSTRAP_ELAPSED_MS_REMAINDER="$(( BOOTSTRAP_ELAPSED_MS % 1000 ))"
printf -v BOOTSTRAP_ELAPSED_FMT "%d.%03d" "$BOOTSTRAP_ELAPSED_S" "$BOOTSTRAP_ELAPSED_MS_REMAINDER"
log "Bootstrap runtime environment complete (${BOOTSTRAP_ELAPSED_FMT}s)"

RUNTIME_VENV="${BOOTSTRAP_RUNTIME_DIR:-/runtime}/.venv"
RUNTIME_PYTHON="$RUNTIME_VENV/bin/python"
if [ ! -x "$RUNTIME_PYTHON" ]; then
    log "ERROR: Runtime Python not found at $RUNTIME_PYTHON"
    exit 1
fi

export PATH="$RUNTIME_VENV/bin:$PATH"
export VIRTUAL_ENV="$RUNTIME_VENV"

# Keep runtime CUDA library path in sync with dynamically bootstrapped venv
export LD_LIBRARY_PATH="$RUNTIME_VENV/lib/python3.13/site-packages/nvidia/cudnn/lib:$RUNTIME_VENV/lib/python3.13/site-packages/torch/lib:${LD_LIBRARY_PATH:-}"

# Drop privileges and run the Python entrypoint
log "Starting application as appuser..."
exec gosu appuser "$RUNTIME_PYTHON" docker/entrypoint.py "$@"
