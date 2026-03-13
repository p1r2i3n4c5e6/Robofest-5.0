# Antigravity Pilot-Centric Drone Control System

This project is a computer vision-based drone control system that identifies a "master pilot" from a video feed and translates their hand gestures into drone commands. It uses a combination of object detection, object tracking, and hand landmark recognition to ensure only the designated pilot can control the drone.

## Project Structure

The codebase is organized into modular components:

*   **`main.py`**: The entry point of the application. It initializes all modules, manages the main video processing loop, and handles the visual coordination (drawing bounding boxes, statuses, etc.).
*   **`vision/camera.py`**: Contains `ThreadedCamera`, which reads frames from the webcam in a separate thread to improve performance and prevent blocking.
*   **`detection/person_detector.py`**: Uses YOLOv8 (optimized with NCNN) to detect people in the camera frame.
*   **`tracking/pilot_tracker.py`**: Implements tracking logic (like ByteTrack) to keep track of identified people. It includes the logic to identify the "master pilot" (e.g., watching for a sustained hand-raising gesture). 
*   **`gesture/hand_processor.py`**: Uses MediaPipe to detect and process hand landmarks. It's optimized to run only on specific regions of interest (ROI) such as the tracked pilot's bounding box.
*   **`control/drone_commander.py`**: Translates the recognized hand gestures into drone control commands, likely using MAVLink or a mock interface for testing.

## How It Works

1.  **Frame Capture**: `vision` module captures frames continuously.
2.  **Person Detection**: `detection` module finds all people in the frame using a lightweight YOLO model (`yolov8n.pt` / `yolov8n_ncnn_model`).
3.  **Pilot Locking**: `tracking` module monitors detected people. It implements a **Sustained Lock** mechanism: you must hold the "NAMASTE" gesture for **5 seconds** to be identified as the pilot. A live countdown appears above your head during this phase.
4.  **Flicker Protection**: The system includes a 10-frame grace period for gestures, preventing accidental resets during momentary detection drops.
5.  **Gesture Recognition**: `gesture` module analyzes ONLY the master pilot's region for hand gestures using MediaPipe Pose (Lite).
6.  **Safety Delays**: Every flight command (ARM, TAKEOFF, etc.) requires a **5-second sustain**. This ensures all drone actions are deliberate and safe.

## Requirements

Refer to `requirements.txt` for the needed Python packages:
*   `opencv-python`
*   `mediapipe`
*   `ncnn`
*   `numpy`
*   `pymavlink`
*    joblib
*    scipy
*    ultralytics

## Running the Application

Execute the main script from the root of this folder:
```bash
python main.py
```
