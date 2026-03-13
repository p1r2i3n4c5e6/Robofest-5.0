import cv2
import time
import numpy as np
from pymavlink import mavutil

# Note: Make sure to install mediapipe and tflite-runtime on Raspberry Pi
# pip3 install mediapipe tflite-runtime pymavlink
import mediapipe as mp
import tflite_runtime.interpreter as tflite

# -------------- CONFIGURATION --------------
CONNECTION_STRING = '/dev/ttyAMA0' # Example for Raspberry Pi UART, adjust if using USB e.g. /dev/ttyACM0
BAUD_RATE = 57600
TFLITE_MODEL_PATH = "gesture_classifier.tflite"
TARGET_ALTITUDE = 2.0 # Fixed altitude in meters
# -------------------------------------------

# Actions dictionary
CLASSES = {
    0: "Hover",
    1: "Move Left",
    2: "Move Right",
    3: "Move Forward",
    4: "Land"
}

# Initialize MediaPipe Pose (Lite model for Raspberry Pi)
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=0, # 0 is CRUCIAL for Raspberry Pi FPS
    enable_segmentation=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def connect_drone():
    print(f"Connecting to drone at {CONNECTION_STRING}...")
    vehicle = mavutil.mavlink_connection(CONNECTION_STRING, baud=BAUD_RATE)
    vehicle.wait_heartbeat()
    print("Heartbeat found! Drone connected.")
    return vehicle

def arm_and_takeoff(vehicle, altitude):
    print("Arming motors...")
    # Change mode to GUIDED
    vehicle.mav.set_mode_send(
        vehicle.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        4 # GUIDED mode number in ArduPilot
    )
    time.sleep(1)
    
    # Arm
    vehicle.mav.command_long_send(
        vehicle.target_system, vehicle.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
        1, 0, 0, 0, 0, 0, 0
    )
    time.sleep(2)
    
    print(f"Taking off to {altitude}m...")
    vehicle.mav.command_long_send(
        vehicle.target_system, vehicle.target_component,
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
        0, 0, 0, 0, 0, 0, altitude
    )

    # In a real scenario, you'd wait until altitude is actually reached.
    print("Ascending... wait 5 seconds...")
    time.sleep(5)
    print("Ready for gesture control.")

def send_velocity(vehicle, velocity_x, velocity_y, velocity_z=0.0):
    """
    Sends velocity commands to the drone.
    X = Forward/Backward, Y = Right/Left, Z = Up/Down
    """
    msg = vehicle.mav.set_position_target_local_ned_encode(
        0,       # time_boot_ms
        vehicle.target_system, vehicle.target_component,
        mavutil.mavlink.MAV_FRAME_BODY_NED, # Relative to drone heading
        0b0000111111000111, # Bitmask to enable ONLY velocity
        0, 0, 0, # Position
        velocity_x, velocity_y, velocity_z, # Velocity in m/s
        0, 0, 0, # Acceleration
        0, 0)    # Yaw, Yaw rate
    vehicle.send(msg)

def land_drone(vehicle):
    print("Landing drone...")
    vehicle.mav.command_long_send(
        vehicle.target_system, vehicle.target_component,
        mavutil.mavlink.MAV_CMD_NAV_LAND, 0,
        0, 0, 0, 0, 0, 0, 0
    )

def main():
    # 1. Connect to Drone
    vehicle = connect_drone()
    
    # 2. Takeoff to exactly 2.0 meters
    arm_and_takeoff(vehicle, TARGET_ALTITUDE)

    # 3. Load TFLite Model
    interpreter = tflite.Interpreter(model_path=TFLITE_MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    # 4. Start Camera (Resolution scaled down for Pi Performance)
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    print("Listening for gestures...")
    last_action_time = time.time()
    last_human_seen_time = time.time()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        # Flip and convert frame
        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Process MediaPipe Pose
        results = pose.process(rgb_frame)

        if results.pose_landmarks:
            last_human_seen_time = time.time()

            # Extract normalized coordinates (relative to shoulder center)
            points = np.array([[lmk.x, lmk.y, lmk.z] for lmk in results.pose_landmarks.landmark])
            left_shoulder = points[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
            right_shoulder = points[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
            shoulder_center = (left_shoulder + right_shoulder) / 2
            
            points_normalized = points - shoulder_center
            features = points_normalized.flatten().astype(np.float32)

            # Predict Gesture
            interpreter.set_tensor(input_details[0]['index'], [features])
            interpreter.invoke()
            prediction = interpreter.get_tensor(output_details[0]['index'])[0]
            
            class_id = np.argmax(prediction)
            confidence = prediction[class_id]

            # Require high confidence to move
            if confidence > 0.8:
                action = CLASSES[class_id]
                cv2.putText(frame, f"Action: {action} ({confidence:.2f})", 
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # Command limit: Run only at roughly 5 Hz to not flood flight controller
                if time.time() - last_action_time > 0.2:
                    if class_id == 0: # Hover
                        send_velocity(vehicle, 0, 0, 0)
                    elif class_id == 1: # Left
                        send_velocity(vehicle, 0, -1.0, 0) # Vy = -1.0 m/s
                    elif class_id == 2: # Right
                        send_velocity(vehicle, 0, 1.0, 0)  # Vy = 1.0 m/s
                    elif class_id == 3: # Forward
                        send_velocity(vehicle, 1.0, 0, 0)  # Vx = 1.0 m/s
                    elif class_id == 4: # Land
                        land_drone(vehicle)
                        break # Exit sequence
                        
                    last_action_time = time.time()

        else:
            # Failsafe: If no human seen for > 1.5 seconds, HOVER immediately
            if time.time() - last_human_seen_time > 1.5:
                cv2.putText(frame, "FAILSAFE: NO HUMAN - HOVERING", 
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                if time.time() - last_action_time > 0.2:
                    send_velocity(vehicle, 0, 0, 0)
                    last_action_time = time.time()

        # Display (optional on Pi, disabled for max FPS via headless setup)
        cv2.imshow("Drone view", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            send_velocity(vehicle, 0, 0, 0) # hover before quitting
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Disconnected.")

if __name__ == "__main__":
    main()
