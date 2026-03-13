#!/usr/bin/env python3
"""
NCNN Frisbee Detector for Raspberry Pi
Sends detection data to Mini Pix FC via MAVLink STATUSTEXT over USB.
The FC then relays it to the laptop GCS over its Telemetry 1 radio.
"""
import time
import cv2
import numpy as np
import ncnn
from pymavlink import mavutil

# --- CONFIGURATION ---
# Serial port where Mini Pix is connected via USB
FC_SERIAL_PORT = "/dev/ttyUSB0"
FC_BAUD = 57600

# NCNN Model files (relative to script location)
MODEL_PARAM = "nanodet_int8/nanodet-opt.param"
MODEL_BIN = "nanodet_int8/nanodet-opt.bin"

# Detection Config
TARGET_CLASS_ID = 0   # Change to match your frisbee class ID in the model
CONFIDENCE_THRESHOLD = 0.5

# Camera Resolution
FRAME_WIDTH = 320
FRAME_HEIGHT = 240
INPUT_SIZE = 320


def send_ai_detection(mav_conn, cx, cy, fw, fh):
    """
    Sends a MAVLink STATUSTEXT message with the detection data.
    Format: AI_DETECT:CX,CY,FRAME_W,FRAME_H
    The FC will relay this over Telemetry 1 to the laptop GCS.
    """
    text = f"AI_DETECT:{cx},{cy},{fw},{fh}"
    mav_conn.mav.statustext_send(
        mavutil.mavlink.MAV_SEVERITY_INFO,
        text.encode("utf-8")
    )


def main():
    print("[AI Pilot] Starting NCNN Frisbee Detector (MAVLink Mode)...")

    # 1. Connect to Mini Pix FC over USB
    print(f"[AI Pilot] Connecting to FC at {FC_SERIAL_PORT}...")
    mav_conn = mavutil.mavlink_connection(FC_SERIAL_PORT, baud=FC_BAUD)
    mav_conn.wait_heartbeat(timeout=10)
    print(f"[AI Pilot] Heartbeat from FC (System {mav_conn.target_system})")

    # 2. Load NCNN Model
    print("[AI Pilot] Loading NCNN Model...")
    net = ncnn.Net()
    net.load_param(MODEL_PARAM)
    net.load_model(MODEL_BIN)

    # 3. Open Camera
    print("[AI Pilot] Opening Camera...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[AI Pilot] FAILED TO OPEN CAMERA")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    print("[AI Pilot] Camera & Model Ready. Running Inference Loop...")

    last_send_time = 0

    # 4. Inference Loop
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Preprocess
            img = cv2.resize(frame, (INPUT_SIZE, INPUT_SIZE))
            mat_in = ncnn.Mat.from_pixels(
                img, ncnn.Mat.PixelType.PIXEL_BGR2RGB, INPUT_SIZE, INPUT_SIZE
            )
            mean_vals = [103.53, 116.28, 123.675]
            norm_vals = [0.017429, 0.017507, 0.017124]
            mat_in.substract_mean_normalize(mean_vals, norm_vals)

            # Inference
            with net.create_extractor() as ex:
                ex.input("data", mat_in)
                ret_code, mat_out = ex.extract("output")

                if ret_code != 0:
                    continue

                detections = []
                if mat_out.dims == 2:
                    for i in range(mat_out.h):
                        values = mat_out.row(i)
                        class_id = int(values[0])
                        score = values[1]

                        if class_id == TARGET_CLASS_ID and score > CONFIDENCE_THRESHOLD:
                            x_min = values[2] * FRAME_WIDTH
                            y_min = values[3] * FRAME_HEIGHT
                            x_max = values[4] * FRAME_WIDTH
                            y_max = values[5] * FRAME_HEIGHT

                            cx = int((x_min + x_max) / 2)
                            cy = int((y_min + y_max) / 2)
                            detections.append((cx, cy, score))

            # Send best detection via MAVLink (rate-limited to 10Hz)
            if detections and (time.time() - last_send_time > 0.1):
                best = max(detections, key=lambda d: d[2])
                cx, cy, conf = best

                send_ai_detection(mav_conn, cx, cy, FRAME_WIDTH, FRAME_HEIGHT)
                print(f"[{time.strftime('%H:%M:%S')}] SENT AI_DETECT: CX={cx} CY={cy} Conf={conf:.2f}")
                last_send_time = time.time()

    except KeyboardInterrupt:
        print("[AI Pilot] Stopping...")
    finally:
        cap.release()
        mav_conn.close()


if __name__ == "__main__":
    main()
