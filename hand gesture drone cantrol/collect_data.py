import cv2
import mediapipe as mp
import numpy as np
import csv
import os

# Configuration
NUM_CLASSES = 5
# Classes: 0: Hover, 1: Left, 2: Right, 3: Forward, 4: Land
DATASET_PATH = "gesture_dataset.csv"

# Initialize MediaPipe Pose
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1, # 1 for better accuracy on PC while collecting data
    enable_segmentation=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
mp_drawing = mp.solutions.drawing_utils

def process_landmarks(landmarks):
    """
    Extract and normalize landmarks.
    We make them relative to the center of the shoulders to avoid distance scaling issues (2 to 3 meters).
    """
    # Get all 33 landmarks
    points = np.array([[lmk.x, lmk.y, lmk.z] for lmk in landmarks.landmark])
    
    # Calculate shoulder center
    left_shoulder = points[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
    right_shoulder = points[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
    shoulder_center = (left_shoulder + right_shoulder) / 2
    
    # Normalize by subtracting shoulder center
    points_normalized = points - shoulder_center
    
    # Flatten the array to a 1D list of 99 features (33 * 3)
    return points_normalized.flatten().tolist()

def main():
    cap = cv2.VideoCapture(0) # Change to your camera index if needed
    
    print("=========================================")
    print("Body Gesture Dataset Collector")
    print("=========================================")
    print("Press 0-4 to record a frame for that class:")
    print("  0: Hover (Arms down)")
    print("  1: Move Left (Left arm straight out)")
    print("  2: Move Right (Right arm straight out)")
    print("  3: Move Forward (Both arms out / T-Pose)")
    print("  4: Land (Cross arms over chest)")
    print("Press 'q' to quit.")
    print("=========================================")

    # Create CSV and write header if it doesn't exist
    if not os.path.exists(DATASET_PATH):
        with open(DATASET_PATH, mode='w', newline='') as f:
            writer = csv.writer(f)
            header = ["class"] + [f"lmk_{i}_{axis}" for i in range(33) for axis in ['x', 'y', 'z']] # 1 + 99 columns
            writer.writerow(header)

    frame_counts = {int(i): 0 for i in range(NUM_CLASSES)}

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Flip frame horizontally for a selfie-view display
        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Process with MediaPipe
        results = pose.process(rgb_frame)

        if results.pose_landmarks:
            mp_drawing.draw_landmarks(
                frame, 
                results.pose_landmarks, 
                mp_pose.POSE_CONNECTIONS
            )
            
        # Display instructions and counts
        y_offset = 30
        for class_id, count in frame_counts.items():
            cv2.putText(frame, f"Class {class_id}: {count} frames", (10, y_offset), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            y_offset += 30

        cv2.imshow("Gesture Data Collector", frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif ord('0') <= key <= ord('4'):
            if results.pose_landmarks:
                class_id = int(chr(key))
                
                # Extract and normalize landmarks
                features = process_landmarks(results.pose_landmarks)
                
                # Save to CSV
                with open(DATASET_PATH, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([class_id] + features)
                
                frame_counts[class_id] += 1
                print(f"Recorded class {class_id} -> Total: {frame_counts[class_id]}")
            else:
                print("No body detected! Make sure you are in the frame.")

    cap.release()
    cv2.destroyAllWindows()
    print("Data collection finished.\nDataset saved to:", DATASET_PATH)

if __name__ == "__main__":
    main()
