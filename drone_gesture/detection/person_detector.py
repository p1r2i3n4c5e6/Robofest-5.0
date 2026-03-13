import cv2
import numpy as np
import ncnn
from .ncnn_utils import decode_outputs

class PersonDetector:
    """
    Uses YOLOv8n. Supports both standard .pt (via Ultralytics) 
    and compiled NCNN (via direct pyncnn) for high stability.
    """
    def __init__(self, model_path="yolov8n.pt", input_size=(640, 640)):
        self.input_size = input_size
        self.model_path = model_path
        self.confidence_threshold = 0.4
        self.iou_threshold = 0.45
        self.is_ncnn = "ncnn" in model_path.lower()
        
        if self.is_ncnn:
            # Load NCNN network
            import ncnn
            self.net = ncnn.Net()
            self.net.opt.use_vulkan_compute = False # Explicitly disable for stability
            self.net.opt.num_threads = 4
            self.net.load_param(f"{self.model_path}/model.ncnn.param")
            self.net.load_model(f"{self.model_path}/model.ncnn.bin")
            print(f"Initialized Low-Level NCNN YOLOv8 Detector (Vulkan=OFF)")
        else:
            # Load Standard PyTorch YOLO
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
            print(f"Initialized Standard YOLOv8 Detector with model: {self.model_path}")

    def detect(self, frame):
        """
        Receives a BGR frame, runs inference, and returns list of (bbox, confidence).
        """
        if self.is_ncnn:
            import ncnn
            img_h, img_w = frame.shape[:2]
            mat_in = ncnn.Mat.from_pixels_resize(frame, ncnn.Mat.PixelType.PIXEL_BGR2RGB, 
                                                img_w, img_h, self.input_size[0], self.input_size[1])
            mean_vals = [0.0, 0.0, 0.0]
            norm_vals = [1/255.0, 1/255.0, 1/255.0]
            mat_in.substract_mean_normalize(mean_vals, norm_vals)
            
            ex = self.net.create_extractor()
            ex.input("in0", mat_in)
            ret, mat_out = ex.extract("out0")
            if ret != 0:
                print(f"NCNN Inference Error: {ret}")
                return [], []
                
            output = np.array(mat_out)
            bboxes, scores = decode_outputs(output, self.confidence_threshold, self.iou_threshold, 
                                          img_w, img_h, input_size=self.input_size[0])
            return bboxes, scores
        else:
            # Standard YOLO detection
            results = self.model(frame, imgsz=self.input_size[0], conf=self.confidence_threshold, classes=[0], verbose=False)
            bboxes = []
            scores = []
            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    conf = box.conf[0].cpu().numpy()
                    bboxes.append([int(x1), int(y1), int(x2), int(y2)])
                    scores.append(float(conf))
            return bboxes, scores
