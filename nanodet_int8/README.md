# NanoDet Frisbee Detection — Raspberry Pi 4

Single-class **frisbee detection** using NanoDet-Plus + NCNN.  
Optimized for real-time inference on Raspberry Pi 4 with USB camera.

## Quick Start

```bash
# 1. Copy this folder to your Raspberry Pi 4
scp -r nanodet_frisbee_rpi4/ pi@<RPI_IP>:~/

# 2. SSH into RPi4 and build
ssh pi@<RPI_IP>
cd ~/nanodet_frisbee_rpi4
chmod +x build_and_run.sh
./build_and_run.sh

# 3. Run detection
./build_and_run.sh run
```

## Manual Build (if script fails)

```bash
# Install dependencies
sudo apt-get install build-essential cmake git libopencv-dev libprotobuf-dev

# Clone & build ncnn
git clone --depth 1 https://github.com/Tencent/ncnn.git
cd ncnn && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DNCNN_VULKAN=OFF
make -j4 && make install DESTDIR=../install
cd ../..

# Build demo
mkdir build && cd build
cmake .. -Dncnn_DIR=<path_to_ncnnConfig.cmake_dir>
make -j4

# Copy model files
cp ../nanodet-opt.param nanodet.param
cp ../nanodet-opt.bin nanodet.bin

# Run
./nanodet_demo 0 0
```

## Modes

| Mode | Command | Description |
|------|---------|-------------|
| Webcam | `./nanodet_demo 0 0` | USB camera (cam ID 0) |
| Image | `./nanodet_demo 1 image.jpg` | Single image |
| Video | `./nanodet_demo 2 video.mp4` | Video file |
| Benchmark | `./nanodet_demo 3 0` | Speed test |

## Model Info

- **Architecture**: NanoDet-Plus (ShuffleNetV2 + GhostPAN)
- **Class**: frisbee (1 class)
- **Input**: 320×320
- **Strides**: 8, 16, 32, 64
- **reg_max**: 7

## Files

| File | Description |
|------|-------------|
| `nanodet-opt.param` | NCNN model graph (optimized) |
| `nanodet-opt.bin` | NCNN model weights |
| `main.cpp` | Demo with FPS display, webcam/video/image modes |
| `nanodet.cpp` | Detection engine (preprocess, decode, NMS) |
| `nanodet.h` | Config (input_size, num_class, strides, labels) |
| `CMakeLists.txt` | Build configuration |
| `build_and_run.sh` | One-click build & run script |
