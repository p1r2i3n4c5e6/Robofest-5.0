import socket
import json
import time

UDP_IP = "127.0.0.1"
UDP_PORT = 5005

print(f"Sending dummy AI detection to GCS at {UDP_IP}:{UDP_PORT}...")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = {
    "detected": True,
    "cx": 160,
    "cy": 120,
    "frame_w": 320,
    "frame_h": 240,
    "timestamp": time.time()
}

sock.sendto(json.dumps(payload).encode(), (UDP_IP, UDP_PORT))
print("Packet sent!")
