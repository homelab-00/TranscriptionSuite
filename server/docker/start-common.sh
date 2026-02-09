#!/bin/bash
# TranscriptionSuite - Shared startup logic for local/remote server modes.
# Usage: ./start-common.sh <local|remote>

set -e

MODE="${1:-}"
if [[ "$MODE" != "local" && "$MODE" != "remote" ]]; then
    echo "Usage: $0 <local|remote>" >&2
    exit 2
fi
shift || true

# ============================================================================
# Constants
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_IMAGE="ghcr.io/homelab-00/transcriptionsuite-server:latest"
CONTAINER_NAME="transcriptionsuite-container"
HF_DIARIZATION_TERMS_URL="https://huggingface.co/pyannote/speaker-diarization-community-1"

# ============================================================================
# Helper Functions
# ============================================================================
print_status() {
    echo -e "\033[1;32m==>\033[0m $1"
}

print_error() {
    echo -e "\033[1;31mError:\033[0m $1" >&2
}

print_info() {
    echo -e "\033[1;34mInfo:\033[0m $1"
}

find_config() {
    local config_file=""
    local config_dir=""
    local dev_config="$SCRIPT_DIR/../config.yaml"

    if [[ -f "$dev_config" ]]; then
        config_file="$dev_config"
        config_dir="$(cd "$SCRIPT_DIR/.." && pwd)"
        print_info "Using development config: $config_file"
    elif [[ -f "$SCRIPT_DIR/config.yaml" ]]; then
        config_file="$SCRIPT_DIR/config.yaml"
        config_dir="$SCRIPT_DIR"
        print_info "Using config: $config_file"
    elif [[ -f "$HOME/.config/TranscriptionSuite/config.yaml" ]]; then
        config_file="$HOME/.config/TranscriptionSuite/config.yaml"
        config_dir="$HOME/.config/TranscriptionSuite"
        print_info "Using user config: $config_file"
    else
        if [[ "$MODE" == "remote" ]]; then
            print_error "No config.yaml found"
            echo ""
            echo "Checked locations:"
            echo "  1. $dev_config (development)"
            echo "  2. $SCRIPT_DIR/config.yaml (script directory)"
            echo "  3. $HOME/.config/TranscriptionSuite/config.yaml (user config)"
            echo ""
            echo "For end users: Run setup.sh first to create the config file."
            echo "For development: config.yaml should be in server/ directory."
            exit 1
        fi
        print_info "No config.yaml found (using container defaults)"
    fi

    CONFIG_FILE="$config_file"
    CONFIG_DIR_TO_MOUNT="$config_dir"
}

find_env_file() {
    local env_file=""
    local dev_env="$SCRIPT_DIR/../.env"

    if [[ -f "$dev_env" ]]; then
        env_file="$dev_env"
    elif [[ -f "$SCRIPT_DIR/.env" ]]; then
        env_file="$SCRIPT_DIR/.env"
    elif [[ -f "$HOME/.config/TranscriptionSuite/.env" ]]; then
        env_file="$HOME/.config/TranscriptionSuite/.env"
    fi

    ENV_FILE="$env_file"
}

read_env_var() {
    local key="$1"
    if [[ -z "$ENV_FILE" || ! -f "$ENV_FILE" ]]; then
        echo ""
        return
    fi
    grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d'=' -f2-
}

upsert_env_var() {
    local key="$1"
    local value="$2"
    local tmp_file
    tmp_file="$(mktemp)"

    if [[ ! -f "$ENV_FILE" ]]; then
        touch "$ENV_FILE"
    fi

    if grep -q -E "^${key}=" "$ENV_FILE"; then
        awk -v k="$key" -v v="$value" '
            BEGIN { updated = 0 }
            {
                if ($0 ~ "^" k "=") {
                    if (updated == 0) {
                        print k "=" v
                        updated = 1
                    }
                } else {
                    print $0
                }
            }
            END {
                if (updated == 0) {
                    print k "=" v
                }
            }
        ' "$ENV_FILE" > "$tmp_file"
        mv "$tmp_file" "$ENV_FILE"
    else
        cat "$ENV_FILE" > "$tmp_file"
        printf "%s=%s\n" "$key" "$value" >> "$tmp_file"
        mv "$tmp_file" "$ENV_FILE"
    fi
}

prepare_hf_token_decision() {
    if [[ -z "$ENV_FILE" ]]; then
        ENV_FILE="$SCRIPT_DIR/.env"
        print_info "No .env file found, creating: $ENV_FILE"
    else
        print_info "Using secrets from: $ENV_FILE"
    fi

    touch "$ENV_FILE"
    ENV_FILE_ARGS=("--env-file" "$ENV_FILE")

    local token decision
    token="$(read_env_var "HUGGINGFACE_TOKEN" | tr -d '\r')"
    decision="$(read_env_var "HUGGINGFACE_TOKEN_DECISION" | tr -d '\r' | tr '[:upper:]' '[:lower:]')"

    if [[ -z "$decision" || ( "$decision" != "unset" && "$decision" != "provided" && "$decision" != "skipped" ) ]]; then
        if [[ -n "$token" ]]; then
            decision="provided"
        else
            decision="unset"
        fi
        upsert_env_var "HUGGINGFACE_TOKEN_DECISION" "$decision"
    fi

    if [[ -n "$token" && "$decision" != "provided" ]]; then
        decision="provided"
        upsert_env_var "HUGGINGFACE_TOKEN_DECISION" "$decision"
    fi

    if [[ -z "$token" && "$decision" == "unset" ]]; then
        if [[ -t 0 && -t 1 ]]; then
            print_info "Optional setup: HuggingFace token enables speaker diarization."
            print_info "Model terms must be accepted first: $HF_DIARIZATION_TERMS_URL"
            print_info "You can skip now and add it later in .env."
            local prompt_token=""
            read -r -p "Enter HuggingFace token (leave empty to skip): " prompt_token
            if [[ -n "$prompt_token" ]]; then
                upsert_env_var "HUGGINGFACE_TOKEN" "$prompt_token"
                upsert_env_var "HUGGINGFACE_TOKEN_DECISION" "provided"
                print_info "HuggingFace token saved."
            else
                upsert_env_var "HUGGINGFACE_TOKEN_DECISION" "skipped"
                print_info "Diarization token setup skipped for now."
            fi
        else
            upsert_env_var "HUGGINGFACE_TOKEN_DECISION" "skipped"
            print_info "Non-interactive startup detected. Marked diarization token setup as skipped."
        fi
    fi
}

apply_uv_cache_compose_mode() {
    local decision="$1"
    local compose_file="$SCRIPT_DIR/docker-compose.yml"
    local cache_dir="/runtime-cache"
    local tmp_file

    if [[ "$decision" == "skipped" ]]; then
        cache_dir="/tmp/uv-cache"
    fi

    # Keep BOOTSTRAP_CACHE_DIR aligned with decision.
    sed -i -E \
        "s|^([[:space:]]*-[[:space:]]*BOOTSTRAP_CACHE_DIR=).*|\\1${cache_dir}|" \
        "$compose_file"

    if [[ "$decision" == "enabled" ]]; then
        if ! grep -Eq '^[[:space:]]*-[[:space:]]*uv-cache:/runtime-cache' "$compose_file"; then
            tmp_file="$(mktemp)"
            awk '
                /-[[:space:]]*(runtime-deps|runtime-cache):\/runtime([[:space:]]|$)/ && !inserted {
                    print $0
                    print "      - uv-cache:/runtime-cache  # Persistent uv cache for delta dependency updates"
                    inserted=1
                    next
                }
                { print $0 }
            ' "$compose_file" > "$tmp_file"
            mv "$tmp_file" "$compose_file"
        fi

        if ! grep -Eq '^  uv-cache:[[:space:]]*$' "$compose_file"; then
            tmp_file="$(mktemp)"
            awk '
                /name:[[:space:]]*transcriptionsuite-runtime/ && !inserted {
                    print $0
                    print "  uv-cache:"
                    print "    name: transcriptionsuite-uv-cache"
                    inserted=1
                    next
                }
                { print $0 }
            ' "$compose_file" > "$tmp_file"
            mv "$tmp_file" "$compose_file"
        fi
    else
        sed -i -E '/^[[:space:]]*-[[:space:]]*uv-cache:\/runtime-cache\b/d' "$compose_file"

        tmp_file="$(mktemp)"
        awk '
            BEGIN { skip = 0 }
            {
                if ($0 ~ /^  uv-cache:[[:space:]]*$/) {
                    skip = 1
                    next
                }
                if (skip == 1) {
                    if ($0 ~ /^  [A-Za-z0-9_.-]+:[[:space:]]*$/) {
                        skip = 0
                        print $0
                        next
                    }
                    if ($0 ~ /^[A-Za-z0-9_.-]+:[[:space:]]*$/) {
                        skip = 0
                        print $0
                        next
                    }
                    next
                }
                print $0
            }
        ' "$compose_file" > "$tmp_file"
        mv "$tmp_file" "$compose_file"
    fi
}

prepare_uv_cache_decision() {
    local decision cache_dir
    decision="$(read_env_var "UV_CACHE_VOLUME_DECISION" | tr -d '\r' | tr '[:upper:]' '[:lower:]')"

    if [[ -z "$decision" || ( "$decision" != "unset" && "$decision" != "enabled" && "$decision" != "skipped" ) ]]; then
        decision="unset"
        upsert_env_var "UV_CACHE_VOLUME_DECISION" "$decision"
    fi

    if [[ "$decision" == "unset" ]]; then
        if docker volume ls --format '{{.Name}}' | grep -q "^transcriptionsuite-uv-cache$"; then
            decision="enabled"
            upsert_env_var "UV_CACHE_VOLUME_DECISION" "$decision"
            print_info "Detected existing UV cache volume. Persistent cache auto-enabled."
        elif [[ -t 0 && -t 1 ]]; then
            print_info "Optional setup: persistent UV cache speeds future updates."
            print_info "Disk usage may grow to ~8GB."
            print_info "Skipping keeps server functionality unchanged but can slow future updates."
            local prompt_choice=""
            while true; do
                read -r -p "Enable UV cache volume? [Y]es / [n]o / [c]ancel: " prompt_choice
                case "${prompt_choice,,}" in
                    ""|y|yes)
                        decision="enabled"
                        break
                        ;;
                    n|no)
                        decision="skipped"
                        break
                        ;;
                    c|cancel)
                        print_info "Startup cancelled."
                        return 1
                        ;;
                    *)
                        print_info "Please answer yes, no, or cancel."
                        ;;
                esac
            done
            upsert_env_var "UV_CACHE_VOLUME_DECISION" "$decision"
        else
            decision="skipped"
            upsert_env_var "UV_CACHE_VOLUME_DECISION" "$decision"
            print_info "Non-interactive startup detected. UV cache setup marked as skipped."
        fi
    fi

    if [[ "$decision" == "enabled" ]]; then
        if ! docker volume ls --format '{{.Name}}' | grep -q "^transcriptionsuite-uv-cache$"; then
            print_info "UV cache volume missing; cold cache expected. Volume will be recreated on start."
        fi
    fi

    if [[ "$decision" == "enabled" ]]; then
        cache_dir="/runtime-cache"
    else
        cache_dir="/tmp/uv-cache"
    fi

    upsert_env_var "BOOTSTRAP_CACHE_DIR" "$cache_dir"
    apply_uv_cache_compose_mode "$decision"
}

check_existing_container_mode() {
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        print_info "Container already exists, checking mode..."

        local current_tls
        current_tls="$(docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep '^TLS_ENABLED=' | cut -d'=' -f2 || echo "false")"

        if [[ "$MODE" == "local" && "$current_tls" == "true" ]]; then
            print_info "Mode conflict: container is in remote/TLS mode, but starting in local mode"
            print_info "Removing existing container..."
            cd "$SCRIPT_DIR"
            docker compose down 2>&1 | grep -v "No resource found to remove" || true
        elif [[ "$MODE" == "remote" && "$current_tls" != "true" ]]; then
            print_info "Mode conflict: container is in local mode, but starting in remote/TLS mode"
            print_info "Removing existing container..."
            cd "$SCRIPT_DIR"
            docker compose down 2>&1 | grep -v "No resource found to remove" || true
        else
            print_info "Container is already in ${MODE} mode"
        fi
    fi
}

# ============================================================================
# Pre-flight Checks
# ============================================================================
if ! docker info &>/dev/null 2>&1; then
    print_error "Docker daemon is not running."
    echo ""
    echo "Please start Docker:"
    echo "  sudo systemctl start docker"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
    print_error "docker-compose.yml not found in $SCRIPT_DIR"
    echo ""
    echo "Run setup.sh first to set up TranscriptionSuite."
    exit 1
fi

# ============================================================================
# Resolve Config/.env
# ============================================================================
CONFIG_FILE=""
CONFIG_DIR_TO_MOUNT=""
ENV_FILE=""
ENV_FILE_ARGS=()
HOST_CERT_PATH=""
HOST_KEY_PATH=""

find_config
find_env_file
prepare_hf_token_decision
if ! prepare_uv_cache_decision; then
    exit 0
fi

export USER_CONFIG_DIR="$CONFIG_DIR_TO_MOUNT"

# ============================================================================
# Remote-mode TLS setup
# ============================================================================
if [[ "$MODE" == "remote" ]]; then
    HOST_CERT_PATH="$(grep -E '^\s+host_cert_path:' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*host_cert_path:[[:space:]]*//' | tr -d '"' | tr -d "'" | tr -d ' ')"
    HOST_KEY_PATH="$(grep -E '^\s+host_key_path:' "$CONFIG_FILE" 2>/dev/null | head -1 | sed 's/.*host_key_path:[[:space:]]*//' | tr -d '"' | tr -d "'" | tr -d ' ')"

    HOST_CERT_PATH="${HOST_CERT_PATH/#\~/$HOME}"
    HOST_KEY_PATH="${HOST_KEY_PATH/#\~/$HOME}"

    if [[ -z "$HOST_CERT_PATH" ]]; then
        print_error "remote_server.tls.host_cert_path is not set in config.yaml"
        echo ""
        echo "Please edit $CONFIG_FILE and set the TLS certificate paths:"
        echo ""
        echo "  remote_server:"
        echo "    tls:"
        echo "      host_cert_path: \"~/.config/Tailscale/my-machine.crt\""
        echo "      host_key_path: \"~/.config/Tailscale/my-machine.key\""
        echo ""
        echo "See README_DEV.md for Tailscale certificate generation instructions."
        exit 1
    fi

    if [[ -z "$HOST_KEY_PATH" ]]; then
        print_error "remote_server.tls.host_key_path is not set in config.yaml"
        echo ""
        echo "Please edit $CONFIG_FILE and set the TLS key path."
        exit 1
    fi

    if [[ ! -f "$HOST_CERT_PATH" ]]; then
        print_error "Certificate file not found: $HOST_CERT_PATH"
        echo ""
        echo "Please ensure the certificate file exists."
        echo "For Tailscale, generate certificates with:"
        echo "  sudo tailscale cert <your-machine>.tail<xxxx>.ts.net"
        exit 1
    fi

    if [[ ! -f "$HOST_KEY_PATH" ]]; then
        print_error "Key file not found: $HOST_KEY_PATH"
        echo ""
        echo "Please ensure the key file exists."
        exit 1
    fi

    print_info "Certificate: $HOST_CERT_PATH"
    print_info "Key: $HOST_KEY_PATH"
fi

# ============================================================================
# Container/Image checks
# ============================================================================
check_existing_container_mode

if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${DOCKER_IMAGE}$"; then
    print_info "Using existing image: $DOCKER_IMAGE"
else
    print_info "Image will be built on first run"
fi

# ============================================================================
# Start Container
# ============================================================================
if [[ "$MODE" == "remote" ]]; then
    print_status "Starting TranscriptionSuite server (remote/TLS mode)..."
    export TLS_ENABLED=true
    export TLS_CERT_PATH="$HOST_CERT_PATH"
    export TLS_KEY_PATH="$HOST_KEY_PATH"
else
    print_status "Starting TranscriptionSuite server (local mode)..."
    export TLS_ENABLED=false
    unset TLS_CERT_PATH
    unset TLS_KEY_PATH
fi

cd "$SCRIPT_DIR"

compose_output=""
if ! compose_output="$(docker compose "${ENV_FILE_ARGS[@]}" up -d 2>&1)"; then
    echo "$compose_output"
    exit 1
fi
echo "$compose_output" | grep -v "WARN\[0000\] No services to build" || true

if [[ "$MODE" == "remote" ]]; then
    echo ""
    echo "=========================================================="
    echo "  TranscriptionSuite Server Started (Remote/TLS Mode)"
    echo "=========================================================="
    echo ""
    echo "  HTTPS URL:   https://localhost:8443"
    echo "  Web UI:      https://localhost:8443/record"
    echo "  Notebook:    https://localhost:8443/notebook"
    echo ""
    echo "  Certificate: $HOST_CERT_PATH"
    echo "  Key:         $HOST_KEY_PATH"
else
    echo ""
    echo "=========================================================="
    echo "  TranscriptionSuite Server Started (Local Mode)"
    echo "=========================================================="
    echo ""
    echo "  Server URL:  http://localhost:8000"
    echo "  Web UI:      http://localhost:8000/record"
    echo "  Notebook:    http://localhost:8000/notebook"
fi

echo ""
echo "  Note: On first run, an admin token will be generated."
echo "        Wait ~10 seconds, then run:"
echo "        docker compose logs | grep \"Admin Token:\""
echo ""
echo "  View logs:   docker compose logs -f"
echo "  Stop:        ./stop.sh"
echo ""
echo "=========================================================="
