import cv2
from flask import Flask, Response

app = Flask(__name__)

# CONFIGURATION
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
PORT = 5000

def generate_frames():
    try:
        cap = cv2.VideoCapture(CAMERA_INDEX)
        # cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        # cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        # cap.set(cv2.CAP_PROP_FPS, 30)
        
        if not cap.isOpened():
            print(f"Error: Could not open camera {CAMERA_INDEX}")
            return

        while True:
            success, frame = cap.read()
            if not success:
                break
                
            # Resize for performance over WiFi
            frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            
            # Encode as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            frame = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                   
    except Exception as e:
        print(f"Stream Error: {e}")
    finally:
        if 'cap' in locals(): cap.release()

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return "<h1>Drone Camera Stream</h1><img src='/video_feed'>"

if __name__ == '__main__':
    #Host 0.0.0.0 allows external access
    print(f"Starting Stream on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
