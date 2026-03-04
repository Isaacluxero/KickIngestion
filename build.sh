#!/usr/bin/env bash
# build.sh — Build images for all layers directly into k3s containerd via nerdctl.
# No external registry needed — nerdctl builds directly into the k8s.io namespace.
#
# Usage:
#   ./build.sh              # build all layers
#   ./build.sh layer1       # build layer1 only (monitor + downloader)
#   ./build.sh layer2       # build kick-analyzer only
#   ./build.sh layer3       # build kick-dashboard only
#   ./build.sh layer4       # build kick-poster only
#   ./build.sh layer5       # build kick-tracker only
#   ./build.sh monitor      # build kick-monitor only (layer1)
#   ./build.sh downloader   # build kick-downloader only (layer1)
#
# Requirements:
#   - nerdctl (for building directly into containerd)
#   - k3s installed and running

set -euo pipefail

build_and_import() {
    local image="$1"
    local context="$2"

    echo ""
    echo "==> Building ${image} from ${context}/"
    sudo nerdctl --namespace k8s.io build -t "${image}" "${context}"

    echo "==> ${image} ready in k3s containerd"
}

build_layer1() {
    build_and_import "kick-monitor:latest"    "./layer1/monitor"
    build_and_import "kick-downloader:latest" "./layer1/downloader"
}

build_layer2() {
    build_and_import "kick-analyzer:latest" "./layer2"
}

build_layer3() {
    build_and_import "kick-dashboard:latest" "./layer3"
}

build_layer4() {
    build_and_import "kick-poster:latest" "./layer4"
}

build_layer5() {
    build_and_import "kick-tracker:latest" "./layer5"
}

TARGET="${1:-all}"

case "$TARGET" in
    all)
        build_layer1
        build_layer2
        build_layer3
        build_layer4
        build_layer5
        ;;
    layer1)
        build_layer1
        ;;
    layer2)
        build_layer2
        ;;
    layer3)
        build_layer3
        ;;
    layer4)
        build_layer4
        ;;
    layer5)
        build_layer5
        ;;
    monitor)
        build_and_import "kick-monitor:latest" "./layer1/monitor"
        ;;
    downloader)
        build_and_import "kick-downloader:latest" "./layer1/downloader"
        ;;
    *)
        echo "Unknown target: $TARGET" >&2
        echo "Use: all | layer1..5 | monitor | downloader" >&2
        exit 1
        ;;
esac

echo ""
echo "==> All done. Verify images:"
echo "    sudo nerdctl --namespace k8s.io images | grep kick"
