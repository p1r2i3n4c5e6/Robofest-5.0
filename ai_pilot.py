import cv2
import time
import threading
import numpy as np
from ultralytics import YOLO
from backend import DroneBackend

# --- CONFIGURATION ---
MODEL_PATH = "yolov8n.pt"  # Assumes model is in the same directory
CONFIDENCE_THRESHOLD = 0.5
TARGET_CLASS_ID = 0  # 0 is usually 'person' in COCO

# STREAMING CONFIG
USE_REMOTE_STREAM = True
RPI_IP = "172.25.137.84"
STREAM_URL = f"http://{RPI_IP}:5000/video_feed"

# STREAMING CONFIG
USE_REMOTE_STREAM = True
RPI_IP = "172.25.137.84"
STREAM_URL = f"http://{RPI_IP}:5000/video_feed"

# AUTO-FRAMING SETTINGS
FRAME_WIDTH = 320
FRAME_HEIGHT = 240
CENTER_X = FRAME_WIDTH // 2
CENTER_Y = FRAME_HEIGHT // 2
DEADZONE_PIXELS = 30   # Reduced for lower resolution
LOCK_DURATION = 1.0    # Seconds to hold lock before geotagging

# PID GAINS (Simple P-Controller for now)
YAW_KP = 0.002       # Rotational speed per pixel error
ALT_KP = 0.002       # Vertical speed per pixel error
MAX_YAW_RATE = 20.0  # deg/s (Need to convert to rad/s or use raw if backend handles it)
                     # Wait, send_velocity takes vx, vy, vz (m/s) in BODY frame.
                     # We can't control Yaw Rate via set_position_target_local_ned velocity fields comfortably
                     # without using the yaw_rate field.
                     # backend.send_velocity sends vx, vy, vz.
                     # We might need to extend backend to send yaw_rate or use set_attitude_target.
                     # However, for simple framing:
                     # YAWing aligns the camera X-axis.
                     # If we can't yaw easily, we can slide Lateral (Vy).
                     # User asked for "framing", usually implies rotation.
                     # Let's check backend.py again. It sends 0 for yaw_rate.
                     # We should modify backend to accept yaw_rate or just slide.
                     # Sliding is often smoother for small corrections.
                     # Let's use Sliding (Vy) for X-error and Vertical (Vz) for Y-error for now.
                     # If User specifically wants Yaw, we need to update backend.

ENABLE_YAW_CONTROL = False # Set True if we implement yaw rate in backend
LATERAL_KP = 0.005 # m/s per pixel error

class AIPilot:
    def __init__(self, backend, mission_mgr=None, callback_frame=None, callback_geotag=None):
        self.backend = backend
        self.mission_mgr = mission_mgr
        self.running = False
        self.thread = None
        self.enabled = False # Toggle from GUI
        
        # Callbacks
        self.callback_frame = callback_frame
        self.callback_geotag = callback_geotag
        
        # Vision State
        self.cap = None
        self.model = None
        self.latest_frame = None
        
        # Logic State
        self.state = "SEARCH" # SEARCH, TRACK, LOCK, GEOTAG
        self.target_locked_time = 0
        self.last_detection_time = 0
        self.resume_mode = None # To store 'AUTO' if we interrupt it
        
        # Output
        self.geotagged_locations = []

    def start(self):
        if self.running: return
        
        print("[AI Pilot] Loading YOLO Model...")
        self.model = YOLO(MODEL_PATH)
        
        print("[AI Pilot] Opening Camera...")
        
        source = STREAM_URL if USE_REMOTE_STREAM else 0
        print(f"[AI Pilot] Opening Camera Source: {source}...")
        
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
             print(f"FAILED TO OPEN CAMERA: {source}")
             # self.cap = cv2.VideoCapture(0) # Fallback?
        else:
             # Some remote streams don't support setting props successfully, but we try
             self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
             self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[AI Pilot] Started.")

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            
    def _loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue
                
            self.latest_frame = frame
            
            # 1. DETECT
            h, w = frame.shape[:2]
            center_x = w // 2
            center_y = h // 2
            
            results = self.model.predict(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
            detections = results[0].boxes
            
            target = None
            # Find best target (e.g., closest to center or highest confidence)
            for box in detections:
                 cls_id = int(box.cls[0])
                 if cls_id == TARGET_CLASS_ID:
                        # Found a human
                        x1, y1, x2, y2 = box.xyxy[0]
                        cx = int((x1 + x2) / 2)
                        cy = int((y1 + y2) / 2)
                        target = (cx, cy, x1, y1, x2, y2)
                        break # Take the first high conf one
            
            # 2. DECIDE & ACT
            self._update_state_machine(target, center_x, center_y)
            
            # 3. VISUALIZE (Optional, for debug view)
            if target:
                cx, cy, _, _, _, _ = target
                cv2.rectangle(frame, (int(target[2]), int(target[3])), (int(target[4]), int(target[5])), (0, 255, 0), 2)
                cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
            
            # Draw Deadzone
            cv2.rectangle(frame, 
                          (center_x - DEADZONE_PIXELS, center_y - DEADZONE_PIXELS),
                          (center_x + DEADZONE_PIXELS, center_y + DEADZONE_PIXELS),
                          (255, 255, 0), 1)
                          
            cv2.putText(frame, f"State: {self.state}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            # CALLBACK OR SHOW
            if self.callback_frame:
                # Convert to RGB for Tkinter/PIL usually, but let's pass BGR or convert here
                # Tkinter usually needs RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.callback_frame(frame_rgb)
            else:
                cv2.imshow("AI Pilot Eyes", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                    
        if not self.callback_frame:
            cv2.destroyAllWindows()

    def _update_state_machine(self, target, center_x, center_y):
        current_time = time.time()
        
        if self.state == "SEARCH":
            if target and self.enabled:
                print("[AI Pilot] Target Detected! Engaging Tracking.")
                
                # PAUSE MISSION
                if self.mission_mgr:
                    self.mission_mgr.pause_mission()
                
                # Ensure GUIDED (Usually already is, but safety check)
                if self.backend.state['mode'] != "GUIDED":
                    self.backend.set_mode("GUIDED")
                    time.sleep(0.2)
                
                self.state = "TRACK"
                
        elif self.state == "TRACK":
            if not target:
                # Lost target
                if current_time - self.last_detection_time > 2.0:
                    print("[AI Pilot] Target Lost. Resuming Mission...")
                    self.state = "SEARCH"
                    self.backend.send_velocity(0, 0, 0) # Stop
                    
                    # RESUME MISSION
                    if self.mission_mgr:
                         self.mission_mgr.resume_mission()
                return

            self.last_detection_time = current_time
            cx, cy, _, _, _, _ = target
            
            # Calculate Errors
            err_x = cx - center_x
            err_y = cy - center_y
            
            # Check if inside Deadzone
            if abs(err_x) < DEADZONE_PIXELS and abs(err_y) < DEADZONE_PIXELS:
                self.state = "LOCK"
                self.target_locked_time = current_time
                # Brake
                self.backend.send_velocity(0, 0, 0)
            else:
                # PID Control
                vy = err_x * LATERAL_KP
                vz = err_y * ALT_KP
                
                # Clamp Limit
                vy = max(min(vy, 1.0), -1.0)
                vz = max(min(vz, 1.0), -1.0)
                
                # Send Command
                self.backend.send_velocity(0, vy, vz)

        elif self.state == "LOCK":
            if not target:
                self.state = "TRACK"
                return

            cx, cy, _, _, _, _ = target
            err_x = cx - center_x
            err_y = cy - center_y
            
            # Verify still in box
            if abs(err_x) > DEADZONE_PIXELS or abs(err_y) > DEADZONE_PIXELS:
                self.state = "TRACK" # Drifted out
                return
                
            # Check Timer
            if current_time - self.target_locked_time >= LOCK_DURATION:
                self.state = "GEOTAG"
                
        elif self.state == "GEOTAG":
            # Perform Geotag
            lat = self.backend.state['lat']
            lon = self.backend.state['lon']
            alt = self.backend.state['alt_rel']
            
            print(f"!!! GEOTAGGED TARGET !!! At {lat}, {lon}")
            self.geotagged_locations.append((lat, lon, alt, time.ctime()))
            
            # CALLBACK TO GUI
            if self.callback_geotag:
                self.callback_geotag(lat, lon)
            
            # Save Image
            if self.latest_frame is not None:
                filename = f"geotag_{int(current_time)}.jpg"
                try: # Write image
                    cv2.imwrite(filename, self.latest_frame)
                    print(f"Saved evidence: {filename}")
                except:
                    pass
            
            print("[AI Pilot] Resume Search/Mission...")
            time.sleep(1) # Hover a bit
            
            # RESUME MISSION
            if self.mission_mgr:
                 self.mission_mgr.resume_mission()
            
            # Reset state
            self.state = "SEARCH"
            
if __name__ == "__main__":
    # Standalone Test
    print("Initializing Backend...")
    backend = DroneBackend() # Default connection
    backend.start()
    
    # Wait for connection
    try:
        while not backend.connected:
            time.sleep(1)
            print("Waiting for drone...")
            
        pilot = AIPilot(backend)
        pilot.start()
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("Stopping...")
        if 'pilot' in locals(): pilot.stop()
        backend.stop()
