import cv2
import mediapipe as mp
import numpy as np
import joblib
from collections import deque
import os

class PoseProcessor:
    """
    Uses MediaPipe Pose to extract body landmarks and classifies gestures
    using a custom 16-feature TFLite model with feature scaling.
    """
    def __init__(self, model_path='gesture_model1.tflite', scaler_path='scaler.save'):
        # 1. Init MediaPipe Pose
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7,
            model_complexity=0
        )
        self.mp_draw = mp.solutions.drawing_utils
        
        # 2. Init OpenCV DNN for TFLite inference (Lightweight)
        try:
            self.net = cv2.dnn.readNetFromTFLite(model_path)
            print(f"[SYSTEM] OpenCV DNN loaded TFLite model: {model_path}")
        except Exception as e:
            print(f"[ERROR] Failed to load model via OpenCV: {e}")
            self.net = None
        
        # 3. Load Scaler
        self.scaler = None
        if os.path.exists(scaler_path):
            try:
                # Check for dummy
                fsize = os.path.getsize(scaler_path)
                if fsize < 1000:
                    print(f"[CRITICAL WARNING] '{scaler_path}' looks like a DUMMY file ({fsize} bytes). Gestures will fail!")
                
                self.scaler = joblib.load(scaler_path)
                print(f"[SYSTEM] Loaded feature scaler from: {scaler_path}")
            except Exception as e:
                print(f"[WARNING] Failed to load scaler: {e}")
        else:
            print(f"[WARNING] Scaler file {scaler_path} not found. Running without scaling.")

        # 4. Prediction Smoothing (Per-Person ID)
        self.buffers = {} 
        self.last_predictions = {}
        self.command_stability = {}
        
        self.gesture_names = {
            0: "ARM", 1: "TAKEOFF", 2: "STOP", 3: "SWARM", 4: "NO_GESTURE", 5: "NAMASTE"
        }

    def get_last_prediction(self, tracker_id):
        return self.last_predictions.get(tracker_id, {"label": "N/A", "confidence": 0.0})

    def _softmax(self, values):
        shifted = values - np.max(values)
        exp_values = np.exp(shifted)
        total = np.sum(exp_values)
        if total <= 0:
            return np.ones_like(values) / len(values)
        return exp_values / total

    def detect_namaste_pose(self, pose_landmarks):
        lm = pose_landmarks.landmark

        lw = lm[self.mp_pose.PoseLandmark.LEFT_WRIST.value]
        rw = lm[self.mp_pose.PoseLandmark.RIGHT_WRIST.value]
        ls = lm[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        rs = lm[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        lh = lm[self.mp_pose.PoseLandmark.LEFT_HIP.value]
        rh = lm[self.mp_pose.PoseLandmark.RIGHT_HIP.value]

        min_vis = min(lw.visibility, rw.visibility, ls.visibility, rs.visibility)
        if min_vis < 0.20:
            return False, 0.0

        wrist_dist = float(np.hypot(lw.x - rw.x, lw.y - rw.y))
        wrist_mid_x = (lw.x + rw.x) / 2.0
        wrist_mid_y = (lw.y + rw.y) / 2.0

        shoulder_mid_x = (ls.x + rs.x) / 2.0
        shoulder_mid_y = (ls.y + rs.y) / 2.0
        hip_mid_y = (lh.y + rh.y) / 2.0

        close_wrists = wrist_dist < 0.20
        centered_on_torso = abs(wrist_mid_x - shoulder_mid_x) < 0.22
        chest_band = (shoulder_mid_y - 0.20) <= wrist_mid_y <= (hip_mid_y + 0.12)

        close_score = max(0.0, 1.0 - (wrist_dist / 0.28))
        score = 0.7 * close_score + 0.3 * (1.0 if chest_band else 0.0)

        return (close_wrists and (centered_on_torso or chest_band)), float(min(1.0, score))
        

    def extract_features_with_flip(self, landmarks, roi_bbox, frame_shape):
        """
        Calculates 16 features (8 landmarks * 2 [x,y]) in the FLIPPED coordinate space
        matching the user's training pipeline.
        """
        lm = landmarks.landmark
        fh, fw = frame_shape[:2]
        rx1, ry1, rx2, ry2 = roi_bbox
        rw, rh = rx2 - rx1, ry2 - ry1

        # Flip math: In flipped full frame, ROI starts at fw - rx2
        rx1_f = fw - rx2
        
        def to_flipped_full_frame(l_norm_x, l_norm_y):
            # l_norm_x is in flipped crop from MediaPipe
            abs_x_f = l_norm_x * rw + rx1_f
            abs_y = l_norm_y * rh + ry1
            return abs_x_f / fw, abs_y / fh

        ls_raw = lm[self.mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        rs_raw = lm[self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        
        ls_x_f, ls_y = to_flipped_full_frame(ls_raw.x, ls_raw.y)
        rs_x_f, rs_y = to_flipped_full_frame(rs_raw.x, rs_raw.y)

        center_x_f = (ls_x_f + rs_x_f) / 2
        center_y_f = (ls_y + rs_y) / 2

        target_ids = [
            self.mp_pose.PoseLandmark.LEFT_SHOULDER.value,
            self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value,
            self.mp_pose.PoseLandmark.LEFT_ELBOW.value,
            self.mp_pose.PoseLandmark.RIGHT_ELBOW.value,
            self.mp_pose.PoseLandmark.LEFT_WRIST.value,
            self.mp_pose.PoseLandmark.RIGHT_WRIST.value,
            self.mp_pose.PoseLandmark.LEFT_HIP.value,
            self.mp_pose.PoseLandmark.RIGHT_HIP.value
        ]

        features = []
        for i in target_ids:
            l_raw = lm[i]
            x_f, y = to_flipped_full_frame(l_raw.x, l_raw.y)
            features.append(x_f - center_x_f)
            features.append(y - center_y_f)

        features = np.array(features, dtype=np.float32).reshape(1, 16)
        if self.scaler is not None:
            features = self.scaler.transform(features)
        return features

    def process_roi(self, frame, roi_bbox, tracker_id=999, mode="lock"):
        """
        Processes the pilot's ROI using MediaPipe Pose.
        Returns: crop, landmarks, and gesture label.
        mode='lock'   -> permissive NAMASTE detection for pilot lock.
        mode='command'-> strict gesture acceptance to avoid false commands.
        """
        x1, y1, x2, y2 = roi_bbox
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            self.last_predictions[tracker_id] = {"label": "NO_CROP", "confidence": 0.0}
            return crop, None, "None"
            
        # Flip crop to match training (Horizontal mirror)
        # Note: We flip the crop, run pose, then landmarks will be relative to flipped crop.
        # But we must be careful with LEFT/RIGHT if the model expects them flipped.
        # The user's script flips BEFORE pose.process().
        crop_flipped = cv2.flip(crop, 1)
        crop_rgb = cv2.cvtColor(crop_flipped, cv2.COLOR_BGR2RGB)
        result = self.pose.process(crop_rgb)
        
        gesture_label = "None"
        if result.pose_landmarks:
            is_namaste_pose, namaste_score = self.detect_namaste_pose(result.pose_landmarks)

            # Re-map landmarks back to full frame
            # Since we flipped the crop, result.pose_landmarks.landmark[i].x is flipped.
            # We don't really need to un-flip them if the model was trained on flipped images.
            # But the 'roi_bbox' is in un-flipped frame coordinates.
            # This could get messy. Let's simplify and NOT flip at first, 
            # as MediaPipe is usually mirror-invariant for body Pose.
            
            # RE-EVALUATION: The user flips for the model. 
            # If I run Pose on un-flipped crop, landmarks are 'native'.
            # If I then calculate features (x - center_x), the SIGN of X will be swapped.
            # I will flip the crop to match the user's training flow exactly.
            
            # To map back to full-frame, we need to know the 'x' in un-flipped space.
            # x_unflipped = 1.0 - x_flipped (within the crop)
            
            # Map landmarks back to full frame coordinates
            features = self.extract_features_with_flip(result.pose_landmarks, roi_bbox, frame.shape)
            
            # Predict
            if self.net:
                self.net.setInput(features.astype(np.float32))
                output = self.net.forward()[0] # cv2 dnn returns [1, 6] usually
                probs = self._softmax(output.astype(np.float32))
                
                confidence = float(np.max(probs))
                pred = int(np.argmax(probs))
                second_best = float(np.partition(probs, -2)[-2]) if probs.shape[0] > 1 else 0.0
                margin = confidence - second_best
                pred_name = self.gesture_names.get(pred, "???")
                self.last_predictions[tracker_id] = {
                    "label": pred_name,
                    "confidence": confidence,
                    "margin": float(margin),
                    "mode": mode
                }
                
                # Active debugging for User - Silenced for cleaner terminal as per request
                # if confidence > 0.80 and pred_name != "NO_GESTURE":
                #      print(f"[GESTURE DBG] ID {tracker_id}: {pred_name} (Conf: {confidence:.2f})")

                if mode == "lock":
                    # Allow lock-gesture (NAMASTE) to trigger with lower confidence in lock mode.
                    if pred == 5 and confidence >= 0.32 and margin >= 0.03:
                        gesture_label = "NAMASTE"
                    elif confidence >= 0.70 and margin >= 0.10:
                        gesture_label = self.gesture_names.get(pred, "NO_GESTURE")
                    else:
                        gesture_label = "NO_GESTURE"
                else:
                    # Strict command mode to prevent "rounding" to wrong gestures.
                    if tracker_id not in self.command_stability:
                        self.command_stability[tracker_id] = {"pred": None, "count": 0}

                    allowed_command_preds = {0, 1, 2, 3}
                    is_strong_command = (
                        pred in allowed_command_preds
                        and confidence >= 0.35
                        and margin >= 0.05
                    )

                    if is_strong_command:
                        state = self.command_stability[tracker_id]
                        if state["pred"] == pred:
                            state["count"] += 1
                        else:
                            state["pred"] = pred
                            state["count"] = 1

                        gesture_label = self.gesture_names.get(pred, "NO_GESTURE") if state["count"] >= 2 else "NO_GESTURE"
                    else:
                        self.command_stability[tracker_id] = {"pred": None, "count": 0}
                        gesture_label = "NO_GESTURE"

            # Fallback lock gesture from geometry if classifier misses NAMASTE.
            if mode == "lock" and is_namaste_pose:
                gesture_label = "NAMASTE"
                self.last_predictions[tracker_id] = {
                    "label": "NAMASTE_HEUR",
                    "confidence": float(max(namaste_score, self.last_predictions.get(tracker_id, {}).get("confidence", 0.0))),
                    "margin": self.last_predictions.get(tracker_id, {}).get("margin", 0.0),
                    "mode": mode
                }

        if tracker_id not in self.last_predictions:
            self.last_predictions[tracker_id] = {"label": "NO_POSE", "confidence": 0.0}
                
        return crop, result.pose_landmarks, gesture_label

    def draw_landmarks(self, frame, pose_landmarks, roi_bbox):
        """
        Draws landmarks onto the main frame, adjusting coordinates by the ROI offset.
        Note: landmarks are originally from a FLIPPED crop. We must UNFLIP for display.
        """
        if not pose_landmarks:
            return frame
            
        x1, y1, x2, y2 = roi_bbox
        cw, ch = x2 - x1, y2 - y1
        
        for lm in pose_landmarks.landmark:
            # Unflip x: 1.0 - lm.x (since Display is unflipped)
            px = int((1.0 - lm.x) * cw) + x1
            py = int(lm.y * ch) + y1
            cv2.circle(frame, (px, py), 3, (0, 255, 0), -1)
            
        return frame
