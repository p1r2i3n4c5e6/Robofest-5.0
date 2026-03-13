import cv2
import threading
import time

class ThreadedCamera:
    """
    Captures frames in a separate thread to prevent blocking the main CV pipeline.
    Optimized for Raspberry 
    """
    def __init__(self, src=0, width=640, height=480):
        self.src = src
        self.width = width
        self.height = height
        self.stream = cv2.VideoCapture(self.src)
        
        # Optimize for performance where possible
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        
        # Start the thread
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

    def update(self):
        while not self.stopped:
            (self.grabbed, self.frame) = self.stream.read()
            if not self.grabbed:
                self.stopped = True
            time.sleep(0.005) # Yield briefly

    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True
        self.thread.join()
        self.stream.release()

if __name__ == '__main__':
    cam = ThreadedCamera()
    time.sleep(1) # Warmup
    frame = cam.read()
    if frame is not None:
        print(f"Captured frame shape: {frame.shape}")
    cam.stop()
