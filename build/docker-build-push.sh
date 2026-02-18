#!/usr/bin/env bash
# TranscriptionSuite Docker Image Build & Push Script
#
# This script builds the Docker image locally and pushes it to GitHub Container Registry (GHCR).
# It's designed to replace the GitHub Actions workflow due to disk space limitations on free runners.
#
# Prerequisites:
#   1. Docker installed and running
#   2. Logged into GHCR: docker login ghcr.io -u <username>
#
# Usage:
#   ./docker-build-push.sh [TAG]
#   TAG=v0.3.0 ./docker-build-push.sh
#
# Examples:
#   ./docker-build-push.sh           # Pushes the most recently built local image
#   ./docker-build-push.sh v0.3.0    # Pushes local image 'v0.3.0' (fails if missing)
#   TAG=dev ./docker-build-push.sh   # Pushes local image 'dev' (fails if missing)

set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Configuration
readonly IMAGE_NAME="ghcr.io/homelab-00/transcriptionsuite-server"

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
    if ! docker manifest inspect "$IMAGE_NAME:$custom_tag" &> /dev/null 2>&1 && \
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
    
    log_info "Pushing image to GHCR: $IMAGE_NAME:$tag"
    
    if docker push "$IMAGE_NAME:$tag"; then
        log_success "Image pushed successfully: $IMAGE_NAME:$tag"
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
    
    log_info "Tagging image: $IMAGE_NAME:$source_tag → $IMAGE_NAME:$target_tag"
    
    if docker tag "$IMAGE_NAME:$source_tag" "$IMAGE_NAME:$target_tag"; then
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

main() {
    local custom_tag="${1:-${TAG:-}}"
    
    echo "=========================================="
    echo "  TranscriptionSuite Docker Push Only"
    echo "=========================================="
    echo ""
    
    # Run checks
    check_prerequisites
    check_docker_login
    
    # Determine which image to use
    if [[ -z "$custom_tag" ]]; then
        log_info "No tag provided. Searching for most recently built local image..."
        # Get the tag of the most recently created image for this repo
        local recent_tag
        recent_tag=$(docker images --filter "reference=$IMAGE_NAME" --format "{{.Tag}}" | head -n 1)
        
        if [[ -z "$recent_tag" ]]; then
            log_error "No local images found for $IMAGE_NAME"
            exit 1
        fi
        
        custom_tag="$recent_tag"
        log_success "Found most recent image: $IMAGE_NAME:$custom_tag"
    else
        log_info "Checking for local image: $IMAGE_NAME:$custom_tag"
        if ! docker image inspect "$IMAGE_NAME:$custom_tag" > /dev/null 2>&1; then
            log_error "Image not found locally: $IMAGE_NAME:$custom_tag"
            log_info "Please build it first with: docker compose build"
            exit 1
        fi
        log_success "Image found: $IMAGE_NAME:$custom_tag"
    fi
    
    # Push the requested tag
    echo ""
    log_info "Pushing image to GHCR..."
    if ! push_image "$custom_tag"; then
        exit 1
    fi
    
    # Release versions are no longer auto-tagged as 'latest'
    # All images use explicit version tags only
    
    # Success summary
    echo ""
    echo "=========================================="
    log_success "Docker image published successfully!"
    echo "=========================================="
    echo ""
    echo "📦 Registry: GitHub Container Registry (GHCR)"
    echo "🏷️  Tags pushed:"
    echo "   • $IMAGE_NAME:$custom_tag"

    echo ""
    echo "📥 Pull command:"
    echo "   docker pull $IMAGE_NAME:$custom_tag"
    echo ""
    echo "🚀 Update docker-compose.yml to use the new image:"
    echo "   image: $IMAGE_NAME:$custom_tag"
    echo ""
}

# Run main function
main "$@"
