import subprocess
import time
import sys
import math
import os
import threading
from pymavlink import mavutil

# --- SETTINGS ---
BINARY_PATH = "./nanodet_demo"
MODE = "0"  # 0 = Webcam mode
CAM_ID = "0" # Camera ID
CALIBRATION_FILE = "../calibration.yml"

# Hardcoded calibration fallback (640x480 IMX708)
DEFAULT_FX = 950.8
DEFAULT_FY = 950.8
DEFAULT_CX = 320.0
DEFAULT_CY = 240.0

# Global altitude from telemetry
current_altitude = 2.0
altitude_lock = threading.Lock()


# ─── Centroid Tracker ───────────────────────────────────────
class CentroidTracker:
    """Assigns unique IDs to detected objects across frames using greedy centroid matching."""
    def __init__(self, maxDisappeared=5):
        self.nextObjectID = 0
        self.objects = {}       # {id: (cx, cy)}
        self.disappeared = {}   # {id: count}
        self.maxDisappeared = maxDisappeared

    def register(self, centroid):
        self.objects[self.nextObjectID] = centroid
        self.disappeared[self.nextObjectID] = 0
        self.nextObjectID += 1

    def deregister(self, objectID):
        del self.objects[objectID]
        del self.disappeared[objectID]

    def update(self, rects):
        """rects = list of [cx, cy, fw, fh]"""
        if len(rects) == 0:
            for objectID in list(self.disappeared.keys()):
                self.disappeared[objectID] += 1
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)
            return self.objects

        inputCentroids = [(r[0], r[1]) for r in rects]

        if len(self.objects) == 0:
            for c in inputCentroids:
                self.register(c)
        else:
            objectIDs = list(self.objects.keys())
            objectCentroids = list(self.objects.values())
            used_input = set()
            used_objects = set()

            # Greedy matching: for each existing object, find closest new detection
            for i, obj_id in enumerate(objectIDs):
                ox, oy = objectCentroids[i]
                min_dist = 9999
                best_idx = -1
                for j, (ix, iy) in enumerate(inputCentroids):
                    if j in used_input:
                        continue
                    d = math.sqrt((ox - ix)**2 + (oy - iy)**2)
                    if d < min_dist:
                        min_dist = d
                        best_idx = j

                if best_idx != -1 and min_dist < 150:  # 150px movement threshold
                    self.objects[obj_id] = inputCentroids[best_idx]
                    self.disappeared[obj_id] = 0
                    used_input.add(best_idx)
                    used_objects.add(obj_id)

            # Mark unmatched objects as disappeared
            for obj_id in objectIDs:
                if obj_id not in used_objects:
                    self.disappeared[obj_id] += 1
                    if self.disappeared[obj_id] > self.maxDisappeared:
                        self.deregister(obj_id)

            # Register new detections that didn't match any existing object
            for j, centroid in enumerate(inputCentroids):
                if j not in used_input:
                    self.register(centroid)

        return self.objects


# ─── Altitude RX Thread ─────────────────────────────────────
def mavlink_rx_thread(mav):
    global current_altitude
    while True:
        try:
            msg = mav.recv_match(type=['GLOBAL_POSITION_INT', 'VFR_HUD'], blocking=True, timeout=5)
            if msg:
                with altitude_lock:
                    if msg.get_type() == 'GLOBAL_POSITION_INT':
                        current_altitude = max(0.5, msg.relative_alt / 1000.0)
                    elif msg.get_type() == 'VFR_HUD':
                        current_altitude = max(0.5, msg.alt)
        except:
            pass


# ─── MAVLink Connection ─────────────────────────────────────
def get_mav_connection():
    potential_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"]
    BAUD = 57600

    for port in potential_ports:
        print(f"Trying to connect on {port}...")
        try:
            mav = mavutil.mavlink_connection(port, baud=BAUD, source_system=100)
            mav.wait_heartbeat(timeout=2)
            print(f"✅ Connected to FC on {port}")
            return mav
        except Exception as e:
            print(f"  - Failed on {port}")
            continue
    return None


# ─── Load Calibration ───────────────────────────────────────
def load_calibration():
    fx, fy, cx_cam, cy_cam = DEFAULT_FX, DEFAULT_FY, DEFAULT_CX, DEFAULT_CY
    try:
        import re
        with open(CALIBRATION_FILE, 'r') as f:
            content = f.read()
        m_fx = re.search(r"fx:\s+([\d\.]+)", content)
        m_fy = re.search(r"fy:\s+([\d\.]+)", content)
        m_cx = re.search(r"cx:\s+([\d\.]+)", content)
        m_cy = re.search(r"cy:\s+([\d\.]+)", content)
        if m_fx: fx = float(m_fx.group(1))
        if m_fy: fy = float(m_fy.group(1))
        if m_cx: cx_cam = float(m_cx.group(1))
        if m_cy: cy_cam = float(m_cy.group(1))
        
        # Sanity check: if values are tiny (< 10), use defaults
        if fx < 10 or fy < 10:
            print(f"⚠️ Calibration values too small (fx={fx}), using defaults")
            return DEFAULT_FX, DEFAULT_FY, DEFAULT_CX, DEFAULT_CY
        
        print(f"Loaded Calibration: fx={fx:.1f}, fy={fy:.1f}, cx={cx_cam:.1f}, cy={cy_cam:.1f}")
    except Exception as e:
        print(f"Using Default Calibration: fx={fx}, fy={fy}")
    return fx, fy, cx_cam, cy_cam


# ─── Main ───────────────────────────────────────────────────
def main():
    print("--- [RPi AI MAVLink Forwarder] Starting ---")

    fx, fy, cx_cam, cy_cam = load_calibration()

    tracker = CentroidTracker(maxDisappeared=5)
    reported_ids = set()  # Each frisbee ID is geotagged ONLY ONCE

    # MAVLink Init
    mav = get_mav_connection()
    if not mav:
        print("❌ ERROR: Could not find Mini Pix on any USB port (/dev/ttyUSB* or /dev/ttyACM*).")
        print("   Please check your USB cable connection to the Pi!")
        return

    # Start altitude RX thread
    rx_thread = threading.Thread(target=mavlink_rx_thread, args=(mav,), daemon=True)
    rx_thread.start()
    try:
        mav.mav.request_data_stream_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_POSITION, 5, 1
        )
    except:
        pass

    # Start the C++ Binary
    print(f"Launching C++ Inference: {BINARY_PATH} {MODE} {CAM_ID}")
    env = os.environ.copy()
    env["DISPLAY"] = ":0"

    process = subprocess.Popen(
        [BINARY_PATH, MODE, CAM_ID],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=env
    )

    last_send = 0
    last_heartbeat = 0

    # Check process stays alive
    time.sleep(1)
    if process.poll() is not None:
        print(f"❌ ERROR: Binary exited immediately with code {process.returncode}")
        out, _ = process.communicate()
        print(f"--- Process Output ---\n{out}\n---")
        return

    try:
        for line in process.stdout:
            line = line.strip()

            # Send heartbeat to FC every 1 second
            if time.time() - last_heartbeat > 1.0:
                mav.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0
                )
                last_heartbeat = time.time()

            if line.startswith("AI_COORD:"):
                try:
                    payload = line.split(":", 1)[1].strip()
                    if not payload:
                        continue

                    # Parse grouped detections: cx,cy,fw,fh|cx,cy,fw,fh|...
                    rects = []
                    for entry in payload.split("|"):
                        parts = entry.strip().split(",")
                        if len(parts) == 4:
                            rects.append([int(p) for p in parts])

                    if not rects:
                        continue

                    # Update tracker with ALL detections from this frame
                    objects = tracker.update(rects)

                    # Get current altitude
                    with altitude_lock:
                        alt = current_altitude

                    for obj_id, (ocx, ocy) in objects.items():
                        # ── SINGLE GEOTAG: skip if already reported ──
                        if obj_id in reported_ids:
                            continue

                        # Find the matching rect for this centroid (for fw, fh)
                        fw, fh = 50, 50
                        for r in rects:
                            if r[0] == ocx and r[1] == ocy:
                                fw, fh = r[2], r[3]
                                break

                        # Calculate pose using altitude (stable projection)
                        x_dist = ((ocx - cx_cam) * alt) / fx
                        y_dist = ((ocy - cy_cam) * alt) / fy

                        # Send via MAVLink — ONLY ONCE per unique ID
                        msg = f"AI_DETECT:{obj_id},{ocx},{ocy},{fw},{fh},{x_dist:.2f},{y_dist:.2f},{alt:.2f}"
                        print(f"🚀 [{time.strftime('%H:%M:%S')}] ID {obj_id} | X:{x_dist:.2f}m Y:{y_dist:.2f}m Alt:{alt:.2f}m")
                        mav.mav.statustext_send(
                            mavutil.mavlink.MAV_SEVERITY_INFO,
                            msg.encode('utf-8')
                        )
                        reported_ids.add(obj_id)

                except Exception as e:
                    print(f"Parse error: {e}")

            elif "Error" in line or line.startswith("["):
                print(f"[C++] {line}")

    except KeyboardInterrupt:
        print("Stopping...")
        process.terminate()
    finally:
        process.kill()
        print("Done.")


if __name__ == "__main__":
    main()
