#!/bin/bash
# ============================================================================
# NanoDet Frisbee Detection - Raspberry Pi 4 Build & Run Script
# ============================================================================
# This script installs dependencies, builds ncnn from source, compiles the
# frisbee detection demo, and runs it on your USB camera.
#
# Usage:
#   chmod +x build_and_run.sh
#   ./build_and_run.sh        # Build everything
#   ./build_and_run.sh run    # Just run (after building)
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NCNN_DIR="$SCRIPT_DIR/ncnn"
BUILD_DIR="$SCRIPT_DIR/build"

# ── Colors for output ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Just run mode ──────────────────────────────────────────────────────────
if [ "$1" = "run" ]; then
    if [ ! -f "$BUILD_DIR/nanodet_demo" ]; then
        error "Build first: ./build_and_run.sh"
    fi
    cd "$BUILD_DIR"
    # Use all 4 RPi4 cores for maximum performance
    export OMP_NUM_THREADS=4
    export OMP_WAIT_POLICY=ACTIVE
    info "Starting Frisbee Detection (4 threads, Press ESC to quit)..."
    ./nanodet_demo 0 0
    exit 0
fi

# ── Step 1: Install dependencies ──────────────────────────────────────────
info "Step 1/4: Installing dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    build-essential cmake git \
    libopencv-dev \
    libprotobuf-dev protobuf-compiler \
    libgomp1

# ── Step 2: Clone & build ncnn ────────────────────────────────────────────
if [ ! -d "$NCNN_DIR" ]; then
    info "Step 2/4: Cloning ncnn..."
    git clone --depth 1 https://github.com/Tencent/ncnn.git "$NCNN_DIR"
else
    info "Step 2/4: ncnn already cloned, skipping..."
fi

info "Building ncnn..."
mkdir -p "$NCNN_DIR/build"
cd "$NCNN_DIR/build"
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DNCNN_BUILD_TOOLS=OFF \
    -DNCNN_BUILD_EXAMPLES=OFF \
    -DNCNN_BUILD_BENCHMARK=OFF \
    -DNCNN_VULKAN=OFF \
    -DNCNN_OPENMP=ON
make -j$(nproc)
make install DESTDIR="$NCNN_DIR/install"

# Find the ncnn cmake config
NCNN_CMAKE=$(find "$NCNN_DIR/install" -name "ncnnConfig.cmake" -exec dirname {} \; | head -1)
if [ -z "$NCNN_CMAKE" ]; then
    error "Could not find ncnnConfig.cmake after build!"
fi
info "ncnn cmake dir: $NCNN_CMAKE"

# ── Step 3: Build frisbee detection demo ──────────────────────────────────
info "Step 3/4: Building frisbee detection demo..."
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
cmake "$SCRIPT_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -Dncnn_DIR="$NCNN_CMAKE"
make -j$(nproc)

# Copy model files
cp "$SCRIPT_DIR/nanodet-opt.param" "$BUILD_DIR/nanodet.param"
cp "$SCRIPT_DIR/nanodet-opt.bin" "$BUILD_DIR/nanodet.bin"

# ── Step 4: Done! ─────────────────────────────────────────────────────────
info "Step 4/4: Build complete!"
echo ""
echo "============================================"
echo "  Frisbee Detection Ready!"
echo "============================================"
echo ""
echo "  Run with USB camera:"
echo "    cd $BUILD_DIR"
echo "    ./nanodet_demo 0 0"
echo ""
echo "  Or use the shortcut:"
echo "    ./build_and_run.sh run"
echo ""
echo "  Controls:"
echo "    ESC = Quit"
echo ""
echo "  Model: NanoDet-Plus (1 class: frisbee)"
echo "  Input: 320x320 | Strides: 8,16,32,64"
echo "============================================"
