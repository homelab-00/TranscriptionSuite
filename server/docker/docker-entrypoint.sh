#!/bin/bash
# Docker entrypoint script for TranscriptionSuite.
#
# This script runs as root to:
# 1) handle TLS certificate permissions,
# 2) install operator-supplied CA certificates into the container trust store,
# 3) bootstrap runtime dependencies into /runtime/.venv,
# 4) drop privileges to appuser and launch the Python server.

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

# Install operator-supplied CA certificates (GH #200). Must happen here: this is the
# only root context in the container, and it must precede bootstrap_runtime.py, which
# makes the first HTTPS request. On a TLS-intercepting network (corporate proxy or
# antivirus HTTPS scanning) nothing downstream can succeed without this.
/usr/bin/python3.13 docker/install_ca_certs.py || true

# Point every HTTPS client at the combined bundle whenever the container carries any
# locally trusted CA — whether bind-mounted just now, or baked into a derived image at
# build time. update-ca-certificates writes system roots AND local CAs into this one
# file, so this adds trust anchors without ever removing the public ones.
#
# These four vars exist because the install path spans three trust stores: uv reads
# SSL_CERT_FILE (and switches itself to native certs when it is set), the git subprocess
# uv shells out to reads GIT_SSL_CAINFO, and the requests client huggingface_hub uses
# for model downloads reads REQUESTS_CA_BUNDLE/CURL_CA_BUNDLE — it honors neither of the
# others. Exporting here covers bootstrap, its child processes, and the server alike.
if compgen -G "/usr/local/share/ca-certificates/*.crt" > /dev/null; then
    SYSTEM_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"
    export SSL_CERT_FILE="${SSL_CERT_FILE:-$SYSTEM_CA_BUNDLE}"
    export GIT_SSL_CAINFO="${GIT_SSL_CAINFO:-$SYSTEM_CA_BUNDLE}"
    export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$SYSTEM_CA_BUNDLE}"
    export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-$SYSTEM_CA_BUNDLE}"
    log "Locally trusted CA detected — HTTPS clients pointed at $SYSTEM_CA_BUNDLE"
fi

# Ensure runtime directories are writable by appuser.
# Do NOT chown /user-config because it is typically a host bind mount
# and changing ownership here can break host-side dashboard permissions.
mkdir -p /data /models /user-config /runtime /runtime/cache
chown -R appuser:appuser /data /models /runtime

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

# Keep runtime CUDA library path in sync with dynamically bootstrapped venv.
# Issue #83 EC-4 fallback: if the canonical python3.13 cuDNN/torch paths are
# empty (future wheel layouts, renamed Python minor version, etc.) glob for
# any python*/site-packages/nvidia/cudnn/lib with actual libcudnn* content.
# Keeps ctranslate2/faster-whisper loadable even if the baked ENV path drifts.
CUDNN_LIB_DIR="$RUNTIME_VENV/lib/python3.13/site-packages/nvidia/cudnn/lib"
TORCH_LIB_DIR="$RUNTIME_VENV/lib/python3.13/site-packages/torch/lib"

if [ ! -d "$CUDNN_LIB_DIR" ] || ! compgen -G "$CUDNN_LIB_DIR/libcudnn*.so*" > /dev/null; then
    discovered_cudnn=""
    for candidate in "$RUNTIME_VENV"/lib/python*/site-packages/nvidia/cudnn/lib; do
        [ -d "$candidate" ] || continue
        if compgen -G "$candidate/libcudnn*.so*" > /dev/null; then
            discovered_cudnn="$candidate"
            break
        fi
    done
    if [ -n "$discovered_cudnn" ]; then
        log "cuDNN libs not at $CUDNN_LIB_DIR — glob-discovered: $discovered_cudnn"
        CUDNN_LIB_DIR="$discovered_cudnn"
    else
        log "WARNING: cuDNN libs not found in $RUNTIME_VENV — ctranslate2 may fail to load"
    fi
fi

if [ ! -d "$TORCH_LIB_DIR" ]; then
    for candidate in "$RUNTIME_VENV"/lib/python*/site-packages/torch/lib; do
        [ -d "$candidate" ] || continue
        TORCH_LIB_DIR="$candidate"
        break
    done
fi

export LD_LIBRARY_PATH="$CUDNN_LIB_DIR:$TORCH_LIB_DIR:${LD_LIBRARY_PATH:-}"

# Drop privileges and run the Python entrypoint
log "Starting application as appuser..."
exec gosu appuser "$RUNTIME_PYTHON" docker/entrypoint.py "$@"
