#!/usr/bin/env bash
# TranscriptionSuite Docker Image Build & Push Script
#
# This script builds the Docker image locally and pushes it to GitHub Container Registry (GHCR).
# It's designed to replace the GitHub Actions workflow due to disk space limitations on free runners.
#
# Note: This script intentionally uses Docker only (not Podman) since it pushes
# to GHCR which requires Docker's credential/manifest tooling.
#
# Prerequisites:
#   1. Docker installed and running
#   2. Logged into GHCR: docker login ghcr.io -u <username>
#
# Usage:
#   ./docker-build-push.sh [--variant default|legacy|vulkan-wsl2|dgx-spark] [--build] [--push|--local-only] [TAG]
#   TAG=v0.3.0 ./docker-build-push.sh
#   VARIANT=legacy ./docker-build-push.sh v0.3.0
#
# Examples:
#   ./docker-build-push.sh                       # Pushes the most recent default image
#   ./docker-build-push.sh v0.3.0                # Pushes local default image 'v0.3.0'
#   ./docker-build-push.sh --variant legacy v0.3.0
#                                                # Pushes local legacy image 'v0.3.0' to
#                                                # ghcr.io/homelab-00/transcriptionsuite-server-legacy
#   ./docker-build-push.sh --variant vulkan-wsl2 v0.3.0
#                                                # Pushes local vulkan-wsl2 image 'v0.3.0' to
#                                                # ghcr.io/homelab-00/transcriptionsuite-server-vulkan-wsl2
#   ./docker-build-push.sh --variant dgx-spark v0.3.0
#                                                # Uses local DGX Spark image 'v0.3.0' by default (no push)
#   ./docker-build-push.sh --variant dgx-spark --build local-dgx
#                                                # Builds DGX image locally only (default for dgx-spark)
#   ./docker-build-push.sh --variant dgx-spark --build --push v0.3.0
#                                                # Builds then pushes DGX image when explicitly requested
#   ./docker-build-push.sh --variant dgx-spark --push v0.3.0
#                                                # Pushes local DGX Spark image 'v0.3.0' to
#                                                # ghcr.io/homelab-00/transcriptionsuite-server-dgx-spark
#   TAG=dev ./docker-build-push.sh               # Pushes local image 'dev'
#
# Variants (Issue #83, GH-101):
#   default     — modern GPUs (cu129 wheels, sm_70..sm_120)
#   legacy      — Pascal/Maxwell support (cu126 wheels, sm_50..sm_90)
#   vulkan-wsl2 — Windows + WSL2 GPU paravirtualization (AMD/Intel); same cu129
#                 server image, GGML transcription via native whisper-server.exe
#   dgx-spark   — Linux ARM64 + Blackwell GB10 (sm_121), NGC PyTorch base
#
# Each non-default variant pushes to a SEPARATE GHCR repo (suffix `-legacy` /
# `-vulkan-wsl2`) so the dashboard's tag selector and version-sort logic stay
# untouched. Each variant auto-tags `latest` only within its own repo.

set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Configuration — repo URL is selected by --variant / VARIANT env (set in main()).
readonly DEFAULT_IMAGE_NAME="ghcr.io/homelab-00/transcriptionsuite-server"
readonly LEGACY_IMAGE_NAME="ghcr.io/homelab-00/transcriptionsuite-server-legacy"
readonly VULKAN_WSL2_IMAGE_NAME="ghcr.io/homelab-00/transcriptionsuite-server-vulkan-wsl2"
readonly DGX_SPARK_IMAGE_NAME="ghcr.io/homelab-00/transcriptionsuite-server-dgx-spark"

# Functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $*"
}

log_success() {
    echo -e "${GREEN}✓${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $*"
}

log_error() {
    echo -e "${RED}✗${NC} $*"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

check_docker_login() {
    log_info "Checking Docker registry authentication..."
    
    # Try docker login status to verify authentication
    if ! docker manifest inspect "${IMAGE_NAME}:$custom_tag" &> /dev/null 2>&1 && \
       ! docker login ghcr.io --get-login &> /dev/null 2>&1; then
        log_warning "Not authenticated with GHCR or image doesn't exist yet"
        log_info "To authenticate, run: docker login ghcr.io -u <username>"
        log_info "Continuing anyway (you'll need auth to push)..."
    else
        log_success "Docker registry authentication verified"
    fi
}

push_image() {
    local tag=$1
    
    log_info "Pushing image to GHCR: ${IMAGE_NAME}:$tag"
    
    if docker push "${IMAGE_NAME}:$tag"; then
        log_success "Image pushed successfully: ${IMAGE_NAME}:$tag"
        return 0
    else
        log_error "Image push failed"
        log_warning "Make sure you're authenticated: docker login ghcr.io -u <username>"
        return 1
    fi
}

tag_image() {
    local source_tag=$1
    local target_tag=$2
    
    log_info "Tagging image: ${IMAGE_NAME}:$source_tag → ${IMAGE_NAME}:$target_tag"
    
    if docker tag "${IMAGE_NAME}:$source_tag" "${IMAGE_NAME}:$target_tag"; then
        log_success "Image tagged successfully"
        return 0
    else
        log_error "Image tagging failed"
        return 1
    fi
}

cleanup_old_images() {
    log_info "Cleaning up dangling images..."
    docker image prune -f &> /dev/null || true
    log_success "Cleanup complete"
}

# Build the image locally with the variant-specific build-arg.
# Used by --build mode; safe to omit when the user has already built the image.
build_image() {
    local image_name=$1
    local tag=$2
    local pytorch_variant=$3
    local base_image=$4
    local uv_python_bin=$5

    # Resolve repo root from this script's location so the build context is correct
    # regardless of the caller's CWD.
    local script_dir repo_root
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    repo_root=$(cd "$script_dir/.." && pwd)

    log_info "Building image: ${image_name}:${tag} (PYTORCH_VARIANT=${pytorch_variant})"
    if docker build \
        --build-arg "PYTORCH_VARIANT=${pytorch_variant}" \
        --build-arg "BASE_IMAGE=${base_image}" \
        --build-arg "UV_PYTHON_BIN=${uv_python_bin}" \
        -t "${image_name}:${tag}" \
        -f "${repo_root}/server/docker/Dockerfile" \
        "${repo_root}"; then
        log_success "Image built: ${image_name}:${tag}"
        return 0
    else
        log_error "Image build failed"
        return 1
    fi
}

print_usage() {
    cat <<'EOF'
Usage:
    ./docker-build-push.sh [--variant default|legacy|vulkan-wsl2|dgx-spark] [--build] [--push|--local-only] [TAG]

Flags:
    --variant {default|legacy|vulkan-wsl2|dgx-spark}
                              Image variant (default: default; or set VARIANT env)
                              default     — modern GPUs (cu129)
                              legacy      — Pascal/Maxwell support (cu126), pushes
                                            to ghcr.io/homelab-00/transcriptionsuite-server-legacy
                              vulkan-wsl2 — Windows + WSL2 GPU (AMD/Intel, cu129),
                                            pushes to ghcr.io/homelab-00/transcriptionsuite-server-vulkan-wsl2
                              dgx-spark   — Linux ARM64 + Blackwell GB10 (sm_121),
                                            NGC base image; pushes to
                                            ghcr.io/homelab-00/transcriptionsuite-server-dgx-spark
  --build                     Build the image locally before pushing (passes
                              --build-arg PYTORCH_VARIANT=<variant>). Without
                              this flag the image is expected to already exist.
    --push                      Push to GHCR after resolving/building the local image.
                                                            Default for default/legacy/vulkan-wsl2 variants.
                                                            Optional (opt-in) for dgx-spark.
    --local-only                Build/resolve local image only; skip GHCR push.
                                                            Default for dgx-spark.
  -h, --help                  Show this help

Tag may also be provided via the TAG env var.
EOF
}

main() {
    local variant="${VARIANT:-default}"
    local do_build=false
    local custom_tag="${TAG:-}"
    local push_mode="auto"

    # Argument parsing — accept flags in any order, with the bare positional TAG last.
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --variant)
                if [[ $# -lt 2 ]]; then
                    log_error "--variant requires a value (default|legacy|vulkan-wsl2|dgx-spark)"
                    exit 1
                fi
                variant="$2"
                shift 2
                ;;
            --variant=*)
                variant="${1#--variant=}"
                shift
                ;;
            --build)
                do_build=true
                shift
                ;;
            --push)
                push_mode="push"
                shift
                ;;
            --local-only)
                push_mode="local"
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            -*)
                log_error "Unknown flag: $1"
                print_usage
                exit 1
                ;;
            *)
                # First bare argument is the tag (preserves backward compat with `./docker-build-push.sh v0.3.0`)
                if [[ -z "$custom_tag" ]]; then
                    custom_tag="$1"
                else
                    log_error "Unexpected extra positional argument: $1"
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # Resolve variant -> repo + build-arg.
    local image_name pytorch_variant variant_label base_image uv_python_bin
    case "$variant" in
        default)
            image_name="$DEFAULT_IMAGE_NAME"
            pytorch_variant="cu129"
            variant_label="default (cu129)"
            base_image="ubuntu:24.04"
            uv_python_bin="/usr/bin/python3.13"
            ;;
        legacy)
            image_name="$LEGACY_IMAGE_NAME"
            pytorch_variant="cu126"
            variant_label="legacy (cu126, sm_50..sm_90 — Pascal/Maxwell)"
            base_image="ubuntu:24.04"
            uv_python_bin="/usr/bin/python3.13"
            ;;
        vulkan-wsl2)
            image_name="$VULKAN_WSL2_IMAGE_NAME"
            # Same cu129 wheels as default — the Vulkan GGML transcription runs in
            # the native whisper-server.exe sidecar, while the main server image
            # still uses PyTorch (diarization, other ASR backends). The dashboard
            # never sets PYTORCH_VARIANT for this profile, so it matches `default`.
            pytorch_variant="cu129"
            variant_label="vulkan-wsl2 (cu129, Windows + WSL2 GPU paravirtualization — AMD/Intel)"
            base_image="ubuntu:24.04"
            uv_python_bin="/usr/bin/python3.13"
            ;;
        dgx-spark)
            image_name="$DGX_SPARK_IMAGE_NAME"
            pytorch_variant="cu129"
            variant_label="dgx-spark (Linux ARM64 + Blackwell GB10, NGC PyTorch base)"
            base_image="nvcr.io/nvidia/pytorch:25.09-py3"
            uv_python_bin="/opt/conda/bin/python"
            # DGX images are large; keep local-only by default.
            if [[ "$push_mode" == "auto" ]]; then
                push_mode="local"
            fi
            ;;
        *)
            log_error "Unknown variant: '$variant'. Expected 'default', 'legacy', 'vulkan-wsl2', or 'dgx-spark'."
            exit 1
            ;;
    esac

    # Make IMAGE_NAME visible to push_image / tag_image (they use ${IMAGE_NAME}).
    IMAGE_NAME="$image_name"

    if [[ "$push_mode" == "auto" ]]; then
        push_mode="push"
    fi

    echo "=========================================="
    echo "  TranscriptionSuite Docker Build & Push"
    echo "=========================================="
    echo ""
    log_info "Variant: ${variant_label}"
    log_info "Target repo: ${image_name}"
    log_info "Publish mode: $([[ "$push_mode" == "push" ]] && echo "push to GHCR" || echo "local-only (no push)")"
    echo ""

    # Run checks
    check_prerequisites
    if [[ "$push_mode" == "push" ]]; then
        check_docker_login
    fi

    # Optional local build — needed for the legacy variant the first time it is published.
    if [[ "$do_build" == true ]]; then
        if [[ -z "$custom_tag" ]]; then
            log_error "--build requires a TAG (positional or via TAG env)"
            exit 1
        fi
        if ! build_image "$image_name" "$custom_tag" "$pytorch_variant" "$base_image" "$uv_python_bin"; then
            exit 1
        fi
    fi

    # Determine which image to use
    if [[ -z "$custom_tag" ]]; then
        log_info "No tag provided. Searching for most recently built local image..."
        # Get the tag of the most recently created image for this repo
        local recent_tag
        recent_tag=$(docker images --filter "reference=${IMAGE_NAME}" --format "{{.Tag}}" | head -n 1)

        if [[ -z "$recent_tag" ]]; then
            log_error "No local images found for ${IMAGE_NAME}"
            if [[ "$variant" != "default" ]]; then
                log_info "For the ${variant} variant, build it first with:"
                log_info "  ./docker-build-push.sh --variant ${variant} --build vX.Y.Z"
                log_info "or manually:"
                log_info "  docker build --build-arg PYTORCH_VARIANT=${pytorch_variant} --build-arg BASE_IMAGE=${base_image} --build-arg UV_PYTHON_BIN=${uv_python_bin} -t ${IMAGE_NAME}:vX.Y.Z -f server/docker/Dockerfile ."
            fi
            exit 1
        fi

        custom_tag="$recent_tag"
        log_success "Found most recent image: ${IMAGE_NAME}:$custom_tag"
    else
        log_info "Checking for local image: ${IMAGE_NAME}:$custom_tag"
        if ! docker image inspect "${IMAGE_NAME}:$custom_tag" > /dev/null 2>&1; then
            log_error "Image not found locally: ${IMAGE_NAME}:$custom_tag"
            log_info "Please build it first with: docker compose build"
            if [[ "$variant" != "default" ]]; then
                log_info "or, for the ${variant} variant:"
                log_info "  ./docker-build-push.sh --variant ${variant} --build $custom_tag"
            fi
            exit 1
        fi
        log_success "Image found: ${IMAGE_NAME}:$custom_tag"
    fi

    if [[ "$push_mode" != "push" ]]; then
        echo ""
        echo "=========================================="
        log_success "Local image ready (push skipped)"
        echo "=========================================="
        echo ""
        echo "Variant: ${variant_label}"
        echo "Local image: ${IMAGE_NAME}:$custom_tag"
        echo ""
        echo "Run with compose (DGX overlay):"
        echo "   IMAGE_REPO=${IMAGE_NAME} TAG=$custom_tag docker compose -f server/docker/docker-compose.yml -f server/docker/docker-compose.linux-host.yml -f server/docker/docker-compose.gpu.yml -f server/docker/docker-compose.dgx-spark.yml up -d"
        echo ""
        return
    fi

    # Push the requested tag
    echo ""
    log_info "Pushing image to GHCR..."
    if ! push_image "$custom_tag"; then
        exit 1
    fi

    # Auto-tag release versions as 'latest' — only within this variant's own repo.
    local tagged_latest=false
    if [[ "$custom_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        log_info "Release version detected — tagging as 'latest' (within ${IMAGE_NAME})..."
        if tag_image "$custom_tag" "latest" && push_image "latest"; then
            tagged_latest=true
        else
            log_warning "Failed to tag/push 'latest' — version tag was pushed successfully"
        fi
    fi

    # Success summary
    echo ""
    echo "=========================================="
    log_success "Docker image published successfully!"
    echo "=========================================="
    echo ""
    echo "Variant: ${variant_label}"
    echo "Registry: GitHub Container Registry (GHCR)"
    echo "Tags pushed:"
    echo "   - ${IMAGE_NAME}:$custom_tag"
    if [[ "$tagged_latest" == true ]]; then
        echo "   - ${IMAGE_NAME}:latest"
    fi

    echo ""
    echo "Pull command:"
    echo "   docker pull ${IMAGE_NAME}:$custom_tag"
    echo ""
    echo "Update docker-compose.yml (or set IMAGE_REPO env) to use the new image:"
    echo "   image: ${IMAGE_NAME}:$custom_tag"
    echo ""

    # GH-99: GHCR defaults new-package visibility to Private. A successful push
    # is NOT proof that anonymous pulls work — that's the failure mode v1.3.3
    # shipped with on the -legacy repo. Always remind the publisher to flip
    # visibility on first push and verify with an anonymous pull.
    local pkg_basename
    pkg_basename="${IMAGE_NAME##*/}"
    log_warning "First-time push to a NEW GHCR package? GHCR defaults visibility to PRIVATE."
    echo "   If this is the first push of ${IMAGE_NAME}, anonymous pulls will return 403."
    echo "   Flip to Public at:"
    echo "     https://github.com/users/homelab-00/packages/container/${pkg_basename}/settings"
    echo ""
    echo "   Verify anonymously (catches private-default + any other publish-gap):"
    echo "     docker logout ghcr.io && docker pull ${IMAGE_NAME}:$custom_tag"
    echo ""
}

# Run main function
main "$@"
