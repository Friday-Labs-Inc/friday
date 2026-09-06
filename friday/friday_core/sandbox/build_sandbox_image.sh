#!/bin/bash
# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Build script for the Friday skill-runtime Docker image.

Usage:
    ./build_sandbox_image.sh            # builds friday/skill-runtime:latest
    ./build_sandbox_image.sh --no-cache # force rebuild from scratch

Prerequisites:
    - Docker daemon must be running
    - Must be run from the frappe/friday_core/sandbox/ directory
      (or pass --dir to specify another location)

Exit codes:
    0  — image built and tagged successfully
    1  — docker not available or build failed
"""

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-friday/skill-runtime}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NO_CACHE=""

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --dir)
            DOCKERFILE_DIR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--no-cache] [--dir <path>]"
            echo "  --no-cache   Do not use Docker cache during build"
            echo "  --dir <path> Directory containing Dockerfile (default: this script's dir)"
            exit 0
            ;;
        *)
            echo "Unknown flag: $1"
            exit 1
            ;;
    esac
done

echo "=== Friday Skill Runtime Image Builder ==="
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Context: ${DOCKERFILE_DIR}"

# Check Docker is available
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker command not found. Is Docker installed and in PATH?"
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "ERROR: Docker daemon is not running or is not accessible."
    echo "Start Docker and try again."
    exit 1
fi

# Check Dockerfile exists
if [[ ! -f "${DOCKERFILE_DIR}/Dockerfile" ]]; then
    echo "ERROR: Dockerfile not found at ${DOCKERFILE_DIR}/Dockerfile"
    exit 1
fi

# Build the image
echo ""
echo "Building image..."
if docker build ${NO_CACHE} -t "${IMAGE_NAME}:${IMAGE_TAG}" "${DOCKERFILE_DIR}"; then
    echo ""
    echo "=== Build successful ==="
    echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
    echo ""
    echo "To push to a registry:"
    echo "  docker push ${IMAGE_NAME}:${IMAGE_TAG}"
    echo ""
    echo "To test locally:"
    echo "  docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} echo 'hello world'"
else
    echo ""
    echo "ERROR: Docker build failed. Check the output above."
    exit 1
fi