#!/bin/bash
# High-Performance MAVLink Deployment for RPi 4
PI_USER="swarm1"
PI_IP="10.20.246.10"
LOCAL_SRC="nanodet_int8/main.cpp"
LOCAL_WRAP="rpi_hover_ai.py"
PI_DEST="~/nanodet/nanodet_frisbee_rpi4/build/"
PI_PARE="~/nanodet/nanodet_frisbee_rpi4/"

echo "--- [1/3] Copying C++ source to Pi at $PI_IP ---"
scp nanodet_int8/*.cpp $PI_USER@$PI_IP:$PI_PARE
scp nanodet_int8/*.h $PI_USER@$PI_IP:$PI_PARE

echo "--- [2.1/3] Copying Models to Pi ---"
scp nanodet_int8/nanodet-opt.param $PI_USER@$PI_IP:$PI_PARE
scp nanodet_int8/nanodet-opt.bin $PI_USER@$PI_IP:$PI_PARE
scp nanodet_int8/build/calibration.yml $PI_USER@$PI_IP:$PI_PARE

echo "--- [2.2/3] Copying rpi_hover_ai.py to Pi ---"
scp $LOCAL_WRAP $PI_USER@$PI_IP:$PI_DEST

echo ""
echo "--- [3/3] Building C++ and Running Pipeline on Pi ---"
echo "Note: This will install pymavlink, pyyaml, GStreamer, build the C++, and start the forwarder."
echo "You will be prompted for your SSH password."
ssh -t $PI_USER@$PI_IP "sudo apt-get update && sudo apt-get install -y libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev gstreamer1.0-libcamera gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-tools gstreamer1.0-x gstreamer1.0-alsa gstreamer1.0-gl gstreamer1.0-gtk3 gstreamer1.0-qt5 gstreamer1.0-pulseaudio && pip3 install pymavlink pyyaml --user --break-system-packages && cd $PI_DEST && cp ../nanodet-opt.param ./nanodet.param && cp ../nanodet-opt.bin ./nanodet.bin && cp ../calibration.yml ./calibration.yml && cmake .. && make -j4 && python3 rpi_hover_ai.py"
