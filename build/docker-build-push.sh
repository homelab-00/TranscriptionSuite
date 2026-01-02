#!/usr/bin/env bash
# TranscriptionSuite Docker Image Build & Push Script
#
# This script builds the Docker image locally and pushes it to GitHub Container Registry (GHCR).
# It's designed to replace the GitHub Actions workflow due to disk space limitations on free runners.
#
# Prerequisites:
#   1. Docker installed and running
#   2. Logged into GHCR: docker login ghcr.io -u <username>
#   3. Run from project root directory
#
# Usage:
#   ./build/docker-build-push.sh [TAG]
#
# Examples:
#   ./build/docker-build-push.sh           # Builds and pushes as 'latest'
#   ./build/docker-build-push.sh v0.3.0    # Builds and pushes as 'v0.3.0' and 'latest'
#   ./build/docker-build-push.sh dev       # Builds and pushes as 'dev'

set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Configuration
readonly IMAGE_NAME="ghcr.io/homelab-00/transcriptionsuite-server"
readonly DOCKERFILE_PATH="server/docker/Dockerfile"

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
    
    # Check if we're in the project root
    if [[ ! -f "$DOCKERFILE_PATH" ]]; then
        log_error "Dockerfile not found at $DOCKERFILE_PATH"
        log_error "Please run this script from the project root directory."
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

check_docker_login() {
    log_info "Checking Docker registry authentication..."
    
    # Try to list repositories to verify authentication
    if ! docker manifest inspect "$IMAGE_NAME:latest" &> /dev/null && \
       ! docker pull "$IMAGE_NAME:latest" &> /dev/null 2>&1; then
        log_warning "Not authenticated with GHCR or image doesn't exist yet"
        log_info "To authenticate, run: docker login ghcr.io -u <username>"
        log_info "Continuing anyway (you'll need auth to push)..."
    else
        log_success "Docker registry authentication verified"
    fi
}

build_image() {
    local tag=$1
    local build_args=$2
    
    log_info "Building Docker image: $IMAGE_NAME:$tag"
    log_info "This may take 15-20 minutes on first build..."
    
    if docker build \
        --file "$DOCKERFILE_PATH" \
        --tag "$IMAGE_NAME:$tag" \
        $build_args \
        .; then
        log_success "Image built successfully: $IMAGE_NAME:$tag"
        return 0
    else
        log_error "Image build failed"
        return 1
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
    local custom_tag="${1:-latest}"
    local is_release=false
    
    echo "=========================================="
    echo "  TranscriptionSuite Docker Build & Push"
    echo "=========================================="
    echo ""
    
    # Check if tag looks like a release version (v*.*.*)
    if [[ "$custom_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        is_release=true
        log_info "Detected release version: $custom_tag"
    else
        log_info "Building with custom tag: $custom_tag"
    fi
    
    # Run checks
    check_prerequisites
    check_docker_login
    
    # Build the image
    echo ""
    log_info "Starting build process..."
    if ! build_image "$custom_tag" ""; then
        exit 1
    fi
    
    # For release versions, also tag as 'latest'
    if [[ "$is_release" == true ]]; then
        echo ""
        if ! tag_image "$custom_tag" "latest"; then
            exit 1
        fi
    fi
    
    # Push all tags
    echo ""
    log_info "Pushing images to GHCR..."
    if ! push_image "$custom_tag"; then
        exit 1
    fi
    
    if [[ "$is_release" == true ]]; then
        if ! push_image "latest"; then
            exit 1
        fi
    fi
    
    # Cleanup
    echo ""
    cleanup_old_images
    
    # Success summary
    echo ""
    echo "=========================================="
    log_success "Docker image published successfully!"
    echo "=========================================="
    echo ""
    echo "📦 Registry: GitHub Container Registry (GHCR)"
    echo "🏷️  Tags pushed:"
    echo "   • $IMAGE_NAME:$custom_tag"
    if [[ "$is_release" == true ]]; then
        echo "   • $IMAGE_NAME:latest"
    fi
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
