import cv2
import time

from vision.camera import ThreadedCamera
from detection.person_detector import PersonDetector
from tracking.pilot_tracker import PilotTracker
from gesture.hand_processor import PoseProcessor
from control.drone_commander import DroneCommander

import os

def main():
    print("=== Antigravity Pilot-Centric Drone Control System ===")

    project_root = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Start Camera Frame Pre-processing (640x480)
    cam = ThreadedCamera(src=0, width=640, height=480)
    time.sleep(1) # Camera warmup
    
    # PERFORMANCE OPTIMIZATION: Check for NCNN folder first for Pi 5 speed
    ncnn_model_dir = os.path.join(project_root, "yolov8n_ncnn_model")
    ncnn_param = os.path.join(ncnn_model_dir, "model.ncnn.param")
    ncnn_bin = os.path.join(ncnn_model_dir, "model.ncnn.bin")
    yolov8_pt = os.path.join(project_root, "yolov8n.pt")
    gesture_model_path = os.path.join(project_root, "gesture_model1.tflite")
    scaler_path = os.path.join(project_root, "scaler.save")

    model_path = ncnn_model_dir if os.path.exists(ncnn_param) and os.path.exists(ncnn_bin) else yolov8_pt
    
    # 2. Init YOLOv8n (Standard or NCNN)
    detector = PersonDetector(model_path=model_path, input_size=(640, 640))
    
    # 3. Init ByteTrack / Pilot tracker logic
    tracker = PilotTracker(frame_height=480, min_height_ratio=0.15)
    
    # 4. Init MediaPipe Pose (Lite model on Pi 5)
    pose_processor = PoseProcessor(model_path=gesture_model_path, scaler_path=scaler_path)
    
    # 5. Init Drone Commander (MAVLink logic)
    commander = DroneCommander(mode="mock")

    print(f"[SYSTEM] Engine: {'NCNN' if detector.is_ncnn else 'PyTorch'}")
    print("[SYSTEM] All modules loaded. Starting main loop...")
    
    frame_count = 0
    start_time = time.time()
    
    # PERFORMANCE OPTIMIZATION: Run YOLO only every N frames
    DETECTION_INTERVAL = 3 
    last_bboxes = []
    last_scores = []
    
    last_pilot_id = None
    current_command_gesture = "None"
    command_gesture_start = time.time()
    gesture_grace_counter = 0
    cmd_state = "hover"
    locked_command = "STOP" # Sticky command state
    failsafe_suspend_counter = 0 # Prevent failsafe spam

    try:
        while True:
            # Step 1: Grab Frame
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue
                
            display_frame = frame.copy()
            
            # Step 2: Adaptive YOLO Detection
            if frame_count % DETECTION_INTERVAL == 0:
                bboxes, scores = detector.detect(frame)
                last_bboxes, last_scores = bboxes, scores
            else:
                bboxes, scores = last_bboxes, last_scores
                
            # Step 3: ByteTrack Pilot Identification
            tracked_objs, frame = tracker.update(frame, bboxes, scores)
            
            # Draw tracking boxes
            for obj in tracked_objs:
                rx1, ry1, rx2, ry2 = obj['bbox']
                color = (255, 255, 0) if obj['id'] == tracker.pilot_id else (0, 0, 255)
                cv2.rectangle(display_frame, (rx1, ry1), (rx2, ry2), color, 1)
            
            # Step 3.5: If Pilot isn't locked, search for Master using "NAMASTE" gesture
            crowd_gestures = {}
            if tracker.pilot_id is None:
                # 1. First Pass: Gather all gestures
                for obj in tracked_objs:
                    if not obj.get('active', True):
                        continue
                    _, _, gesture = pose_processor.process_roi(frame, obj['bbox'], tracker_id=obj['id'], mode="lock")
                    if gesture != "None" and gesture != "NO_GESTURE":
                        crowd_gestures[obj['id']] = gesture

                # 2. Update Tracker (This sets 'lock_progress' in tracked_objs)
                pilot_bbox, is_locked = tracker.get_pilot_roi(tracked_objs, frame, crowd_gesture_data=crowd_gestures)

                # 3. Second Pass: Draw search UI
                for obj in tracked_objs:
                    if not obj.get('active', True):
                        continue
                    gesture = crowd_gestures.get(obj['id'], "None")
                    rx1, ry1, rx2, ry2 = obj['bbox']
                    
                    if gesture != "None":
                        cv2.rectangle(display_frame, (rx1, ry1), (rx2, ry2), (0, 255, 0), 1)
                        cv2.putText(display_frame, f"G: {gesture}", (rx1, ry1-10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

                    dbg = pose_processor.get_last_prediction(obj['id'])
                    cv2.putText(display_frame, f"DBG: {dbg['label']} {dbg['confidence']:.2f}", (rx1, ry1-45),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

                    # Show LOCKING countdown whenever timer has started,
                    # including grace frames where gesture may flicker.
                    if 'lock_progress' in obj:
                        progress = obj['lock_progress']
                        cv2.putText(display_frame, f"LOCKING: {max(0, 5.0 - progress):.1f}s", (rx1, ry1-30), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                cv2.putText(display_frame, "SEARCHING FOR MASTER (Hold NAMASTE 5s)", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            else:
                # If already locked, just get the ROI
                pilot_bbox, is_locked = tracker.get_pilot_roi(tracked_objs, frame)

            # Step 4: Logic for Locked Pilot
            if is_locked and pilot_bbox is not None:
                if tracker.pilot_id != last_pilot_id:
                    print(f"[SYSTEM] Pilot {tracker.pilot_id} LOCKED.")
                    last_pilot_id = tracker.pilot_id
                    current_command_gesture = "None"
                    command_gesture_start = 0

                x1, y1, x2, y2 = pilot_bbox
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 0, 0), 4) # Thick Blue
                cv2.putText(display_frame, f"LOCKED PILOT {tracker.pilot_id}", (x1, max(20, y1-10)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                
                # ROI Cropping & Gesture Recognition
                crop, pose_lms, gesture = pose_processor.process_roi(frame, pilot_bbox, tracker_id=tracker.pilot_id, mode="command")
                if pose_lms:
                    display_frame = pose_processor.draw_landmarks(display_frame, pose_lms, pilot_bbox)

                dbg = pose_processor.get_last_prediction(tracker.pilot_id)
                cv2.putText(display_frame, f"DBG: {dbg['label']} {dbg['confidence']:.2f}", (x1, max(20, y1-35)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                
                # Step 5: Command Translation with STICKY SUSTAIN (5.0s hold to change)
                SUSTAIN_TIME = 5.0 
                GRACE_FRAMES = 45 # Increased to 1.5s to be extremely robust to flicker
                
                # INTENT DETECTION: Use the raw model output for maximum sensitivity
                intent_label = dbg['label'] if (dbg['label'] not in ["NO_GESTURE", "NO_POSE", "None"] and dbg['confidence'] > 0.15) else "None"
                
                if intent_label != "None":
                    if intent_label != current_command_gesture:
                        # User is showing a NEW gesture -> Start the 5s "Charging" timer
                        current_command_gesture = intent_label
                        command_gesture_start = time.time()
                        gesture_grace_counter = 0
                    
                    elapsed = time.time() - command_gesture_start
                    gesture_grace_counter = 0 # Reset grace while gesture is active
                    
                    if elapsed >= SUSTAIN_TIME:
                        # 5-second hold complete -> LOCK the new command
                        if intent_label != locked_command:
                            print(f"\n[STICKY LOCK] Finalized: {intent_label.upper()}")
                            locked_command = intent_label
                            # --- GCS LINK: Trigger Remote Buttons ---
                            commander.send_remote_command(locked_command)
                        
                        cmd_state = commander.parse_gestures(locked_command)
                        cv2.putText(display_frame, f"LOCKED: {locked_command.upper()}", (20, 60), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
                    else:
                        # Sustaining the old command while "Charging" the new one
                        cmd_state = commander.parse_gestures(locked_command)
                        cv2.putText(display_frame, f"LOCKED: {locked_command.upper()}", (20, 60), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
                        # Show charging progress clearly on screen
                        charge_pct = int((elapsed / SUSTAIN_TIME) * 100)
                        cv2.putText(display_frame, f"CHARGING {intent_label.upper()}: {charge_pct}%", (20, 110), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 2)
                        
                        # Terminal feedback for charging (every 10 frames for responsiveness)
                        if frame_count % 10 == 0:
                            print(f"[STATUS] ACTIVE: {locked_command.upper()} | INTENT: {intent_label.upper()} {charge_pct}%")
                else:
                    # NO_GESTURE / None -> Check grace period to keep the charging timer alive
                    if current_command_gesture != "None":
                        gesture_grace_counter += 1
                        if gesture_grace_counter > GRACE_FRAMES:
                            current_command_gesture = "None"
                            gesture_grace_counter = 0
                    
                    # Execute and show the currently locked command
                    cmd_state = commander.parse_gestures(locked_command)
                    cv2.putText(display_frame, f"LOCKED: {locked_command.upper()}", (20, 60), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
                    
                    if current_command_gesture != "None":
                        # We are in grace mode (handling a brief flicker)
                        elapsed = time.time() - command_gesture_start
                        charge_pct = int((elapsed / SUSTAIN_TIME) * 100)
                        cv2.putText(display_frame, f"CHARGING {current_command_gesture.upper()}: {charge_pct}% (GRACE)", (20, 110), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 2)
                
                # Reset failsafe counter since we have a locked pilot
                failsafe_suspend_counter = 0
            else:
                if last_pilot_id is not None:
                    # Pilot just dropped out. Wait 45 frames (~1.5s) to prevent failsafe spam
                    failsafe_suspend_counter += 1
                    if failsafe_suspend_counter > 45: 
                        print(f"\n[FAILSAFE] Pilot {last_pilot_id} lost. Halting.")
                        commander.trigger_failsafe()
                        last_pilot_id = None
                        locked_command = "STOP" # Go to safe state
                        failsafe_suspend_counter = 0
                else:
                    # Search mode
                    cmd_state = commander.parse_gestures("STOP")
                    cv2.putText(display_frame, "SEARCHING PILOT...", (20, 60), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
                    failsafe_suspend_counter = 0

            # Step 6: Finalize Frame
            cv2.imshow("Antigravity Pilot Interface", display_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
            # Periodic Status Update (Strictly Controlled)
            frame_count += 1
            if frame_count % 30 == 0:
                if tracker.pilot_id is not None:
                    # Only print locked status if NOT charging (to avoid double prints)
                    if current_command_gesture == "None" or current_command_gesture == locked_command:
                        print(f"[STATUS] LOCKED: {locked_command.upper()}")
                else:
                    # Search logging
                    if frame_count % 90 == 0:
                        print("[STATUS] SEARCHING FOR MASTER...")
                    preds = pose_processor.last_predictions
                    for pid, pdata in preds.items():
                        if pdata.get('label') == "NAMASTE":
                            print(f"[STATUS] Master candidate ID:{pid} (Hold 5s to Lock)")
                            break

    except KeyboardInterrupt:
        print("[SYSTEM] Caught interrupt. Shutting down cleanly.")
    
    finally:
        cam.stop()
        cv2.destroyAllWindows()
        print("[SYSTEM] Goodbye.")

if __name__ == "__main__":
    main()
