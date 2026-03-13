import socket
import json

class DroneCommander:
    """
    Translates gesture states (e.g., thumb up, open palm, closed fist) 
    into directional commands or statuses.
    """
    def __init__(self, mode="mock"):
        self.mode = mode
        self.state = "hover" # "hover", "forward", "backward", "left", "right"
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"Initialized DroneCommander in {self.mode} mode.")

    def parse_gestures(self, gesture_label):
        """
        Translates a categorical gesture label into a specific control vector.
        """
        self.state = gesture_label
        
        # User defined 6 classes
        if gesture_label == "ARM":
            # print(">>> COMM: ARMING DRONE")
            return self._hover()
        elif gesture_label == "TAKEOFF":
            # print(">>> COMM: TAKEOFF INITIATED")
            return self._hover()
        elif gesture_label == "STOP":
            return self._hover()
        elif gesture_label == "SWARM":
            # print(">>> COMM: TRIGGERING SWARM BEHAVIOR")
            return self._hover()
        elif gesture_label == "NAMASTE": # Used for locking
            return self._hover()
        elif gesture_label == "NO_GESTURE":
            return self._hover()
        else:
            return self._hover()

    def send_remote_command(self, label):
        """Sends the finalized locked gesture to GCS via UDP"""
        try:
            self.udp_sock.sendto(label.upper().encode(), ("127.0.0.1", 5006))
            print(f">>> LINK: Sent {label.upper()} to GCS (Local Bridge)")
        except Exception as e:
            print(f">>> LINK ERROR: {e}")

    def _hover(self):
        self.state = "hover"
        return self._send_command(0.0, 0.0, 0.0, 0.0)

    def trigger_failsafe(self):
        """
        Called when PilotTracker loses ID track for > 1.5s.
        """
        print(">>> COMM: Failsafe triggered. Halting velocity.")
        return self._hover()

    def _send_command(self, vx, vy, vz, yaw):
        if self.mode == "mock":
            # print(f"Drone Command V=({vx},{vy},{vz}) Y={yaw}")
            pass
        elif self.mode == "mavlink":
            # Send to PyMavlink
            pass
        return self.state
