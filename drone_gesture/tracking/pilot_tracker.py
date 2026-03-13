import time
import numpy as np
import cv2
from scipy.spatial import distance as dist

class SimpleCentroidTracker:
    def __init__(self, max_disappeared=30):
        self.next_id = 0
        self.objects = {} # id: (centroid, bbox)
        self.disappeared = {}
        self.max_disappeared = max_disappeared

    def register(self, centroid, bbox):
        self.objects[self.next_id] = (centroid, bbox)
        self.disappeared[self.next_id] = 0
        self.next_id += 1
        return self.next_id - 1

    def update(self, bboxes):
        if len(bboxes) == 0:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    del self.objects[obj_id]
                    del self.disappeared[obj_id]
            return self.objects

        input_centroids = np.zeros((len(bboxes), 2), dtype="int")
        for i, (startX, startY, endX, endY) in enumerate(bboxes):
            cX = int((startX + endX) / 2.0)
            cY = int((startY + endY) / 2.0)
            input_centroids[i] = (cX, cY)

        if len(self.objects) == 0:
            for i in range(0, len(input_centroids)):
                self.register(input_centroids[i], bboxes[i])
        else:
            object_ids = list(self.objects.keys())
            object_centroids = [self.objects[obj_id][0] for obj_id in object_ids]

            D = dist.cdist(np.array(object_centroids), input_centroids)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                
                # Distance threshold for matching (e.g., 100 pixels)
                if D[row, col] > 150:
                    continue

                object_id = object_ids[row]
                self.objects[object_id] = (input_centroids[col], bboxes[col])
                self.disappeared[object_id] = 0
                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(0, D.shape[0])).difference(used_rows)
            unused_cols = set(range(0, D.shape[1])).difference(used_cols)

            for row in unused_rows:
                object_id = object_ids[row]
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    del self.objects[object_id]
                    del self.disappeared[object_id]

            for col in unused_cols:
                self.register(input_centroids[col], bboxes[col])

        return self.objects

class PilotTracker:
    """
    Tracking logic to persistently lock onto the pilot id.
    Includes ID-Swap Prevention via Color Histograms.
    """
    def __init__(self, frame_height, min_height_ratio=0.15):
        self.frame_height = frame_height
        self.min_height_ratio = min_height_ratio
        
        self.pilot_id = None
        self.last_seen_time = time.time()
        self.lost_track_timeout = 1.5
        self.active_disappear_threshold = 8
        
        self.tracker = SimpleCentroidTracker(max_disappeared=30)
        self.pilot_histogram = None
        self.gesture_start_times = {}
        self.gesture_grace_counters = {} # To prevent flickering reset
        
        print("Initialized Pilot Tracker with Centroid & Histogram logic")
        
    def extract_histogram(self, frame, bbox):
        x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Use Hue and Saturation for color profile
        hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist
        
    def update(self, frame, bboxes, scores):
        """
        Receives bboxes from YOLO.
        Matches returning bounding boxes to IDs.
        """
        valid_bboxes = []
        for bbox, score in zip(bboxes, scores):
            x1, y1, x2, y2 = bbox
            h = y2 - y1
            
            # Distance threshold: Ignore tiny figures (less than 15% frame height)
            if h / self.frame_height >= self.min_height_ratio:
                valid_bboxes.append(bbox)
                
        tracked_objects = self.tracker.update(valid_bboxes)
        
        # Convert dictionary to list of dicts for easier processing
        tracked_list = []
        for obj_id, obj_data in tracked_objects.items():
            disappeared = self.tracker.disappeared.get(obj_id, 0)
            tracked_list.append({
                "id": obj_id,
                "bbox": obj_data[1],
                "disappeared": disappeared,
                "active": disappeared <= self.active_disappear_threshold
            })
        return tracked_list, frame
        
    def get_pilot_roi(self, tracked_objects, frame, crowd_gesture_data=None):
        """
        Finds the pilot's ROI based on their locked ID.
        Identifies a new pilot based on a sustained "NAMASTE" gesture.
        """
        if len(tracked_objects) == 0:
            if self.pilot_id is not None:
                print("[FAILSAFE] Locked Pilot left frame. Re-entering Search Mode.")
                self.pilot_id = None
            return None, False

        active_tracked_objects = [obj for obj in tracked_objects if obj.get("active", True)]
            
        # Initial lock-on if pilot_id is None
        if self.pilot_id is None:
            if crowd_gesture_data is None:
                return None, False
                
            active_ids = {obj['id'] for obj in active_tracked_objects}
            # Cleanup for lost IDs
            for lost_id in list(self.gesture_start_times.keys()):
                if lost_id not in active_ids:
                    del self.gesture_start_times[lost_id]
                    if lost_id in self.gesture_grace_counters:
                        del self.gesture_grace_counters[lost_id]

            for obj in active_tracked_objects:
                obj_id = obj['id']
                bbox = obj['bbox']
                
                gesture_name = str(crowd_gesture_data.get(obj_id, "")).strip().upper()
                if gesture_name in {"NAMASTE", "NAMSTE"}:
                    if obj_id not in self.gesture_start_times:
                        self.gesture_start_times[obj_id] = time.time()
                        self.gesture_grace_counters[obj_id] = 0
                    
                    self.gesture_grace_counters[obj_id] = 0 # Reset grace
                    elapsed = time.time() - self.gesture_start_times[obj_id]
                    
                    if elapsed >= 5.0:
                        self.pilot_id = obj_id
                        self.last_seen_time = time.time()
                        self.pilot_histogram = self.extract_histogram(frame, bbox)
                        self.gesture_start_times = {}
                        self.gesture_grace_counters = {}
                        print(f"[TRACKER] Master Lock Finalized! Locked onto Pilot ID: {self.pilot_id}")
                        return bbox, True
                    else:
                        obj['lock_progress'] = elapsed
                        # Debug progress (every ~10 frames roughly if FPS is 10-20)
                        if self.gesture_grace_counters[obj_id] % 10 == 0:
                            print(f"[TRACKER] Tracking NAMASTE for {obj_id}: {elapsed:.1f}/5s")
                else:
                    # Grace period: allow short breaks before resetting
                    if obj_id in self.gesture_start_times:
                        self.gesture_grace_counters[obj_id] = self.gesture_grace_counters.get(obj_id, 0) + 1
                        if self.gesture_grace_counters[obj_id] > 25:
                            print(f"[TRACKER] NAMASTE broken for {obj_id}. Resetting timer.")
                            del self.gesture_start_times[obj_id]
                            del self.gesture_grace_counters[obj_id]
                        else:
                            # Still count as progress during grace!
                            obj['lock_progress'] = time.time() - self.gesture_start_times[obj_id]
            
            return None, False

        # If already locked, find the pilot in current frame
        for obj in active_tracked_objects:
            if obj['id'] == self.pilot_id:
                # Anti-Swap Prevention via Histograms
                current_hist = self.extract_histogram(frame, obj['bbox'])
                if current_hist is not None and self.pilot_histogram is not None:
                    distance = cv2.compareHist(self.pilot_histogram, current_hist, cv2.HISTCMP_BHATTACHARYYA)
                    if distance > 0.6:
                        print(f"[SECURITY] ID Swap Detected! Rejecting ID {self.pilot_id}.")
                        self.pilot_id = None
                        return None, False
                
                if current_hist is not None and self.pilot_histogram is not None:
                     self.pilot_histogram = cv2.addWeighted(self.pilot_histogram, 0.95, current_hist, 0.05, 0.0)

                self.last_seen_time = time.time()
                return obj['bbox'], True
                
        # Pilot lost logic
        time_lost = time.time() - self.last_seen_time
        if time_lost >= self.lost_track_timeout:
            print(f"[FAILSAFE] Locked Pilot left active frame. Re-entering Search Mode.")
            self.pilot_id = None
            
        return None, False
