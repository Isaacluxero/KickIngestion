#!/usr/bin/env bash
# build.sh — Build both images and import them directly into k3s.
# No external registry needed. Uses k3s ctr images import so the images
# are available to k3s's containerd without Docker daemon involvement at runtime.
#
# Usage:
#   ./build.sh              # build + import both images
#   ./build.sh monitor      # build + import kick-monitor only
#   ./build.sh downloader   # build + import kick-downloader only
#
# Requirements:
#   - docker (for building)
#   - k3s installed and running on this machine (for sudo k3s ctr images import)

set -euo pipefail

MONITOR_IMAGE="kick-monitor:latest"
DOWNLOADER_IMAGE="kick-downloader:latest"

TARGET="${1:-all}"

build_and_import() {
    local image="$1"
    local context="$2"

    echo ""
    echo "==> Building ${image} from ./${context}/"
    docker build -t "${image}" "./${context}"

    echo "==> Importing ${image} into k3s containerd..."
    docker save "${image}" | sudo k3s ctr images import -

    echo "==> ${image} imported successfully"
}

case "$TARGET" in
    monitor)
        build_and_import "$MONITOR_IMAGE" "monitor"
        ;;
    downloader)
        build_and_import "$DOWNLOADER_IMAGE" "downloader"
        ;;
    all)
        build_and_import "$MONITOR_IMAGE" "monitor"
        build_and_import "$DOWNLOADER_IMAGE" "downloader"
        ;;
    *)
        echo "Unknown target: $TARGET. Use: all | monitor | downloader" >&2
        exit 1
        ;;
esac

echo ""
echo "==> All done. Verify imported images:"
echo "    sudo k3s ctr images ls | grep kick"
