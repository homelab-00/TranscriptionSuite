#!/bin/bash
# Docker entrypoint script for TranscriptionSuite
# 
# This script runs as root to handle TLS certificate permissions,
# then drops privileges to 'appuser' to run the Python application.

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

# Ensure data directories are owned by appuser
chown -R appuser:appuser /data

# Drop privileges and run the Python entrypoint
log "Starting application as appuser..."
exec gosu appuser python docker/entrypoint.py "$@"
