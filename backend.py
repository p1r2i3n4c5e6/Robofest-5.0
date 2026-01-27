import threading
import time
from pymavlink import mavutil

# --- CONFIGURATION ---
DEFAULT_CONNECTION_STRING = '/dev/ttyACM0'
DEFAULT_BAUD = 57600
TAKEOFF_ALT_DEFAULT = 5.0
TAKEOFF_ALT_DEFAULT = 5.0

import math

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

class DroneBackend:
    """
    Handles Mavlink communication in a separate thread.
    Manages connection, telemetry, and basic commands.
    """
    def __init__(self, drone_id=1, connect_str=DEFAULT_CONNECTION_STRING, baud_rate=DEFAULT_BAUD):
        self.drone_id = drone_id
        self.last_prearm_poll = 0
        self.last_attitude_time = time.time() # Track data flow
        
        # Log Prefix matching GUI expectation [D0] / [D1]
        self.log_prefix = f"[D{self.drone_id-1}]"
        self.connect_str = connect_str
        self.baud_rate = baud_rate
        self.master = None
        self.running = False
        self.connected = False
        
        self.mode = "UNKNOWN"
        self.state = {
            'lat': 0, 'lon': 0, 'alt': 0, 'alt_rel': 0, 
            'pitch': 0, 'roll': 0, 'yaw': 0, 'heading': 0,
            'speed': 0, 'climb': 0,
            'gps_fix': 0, 'gps_sats': 0, 'gps_hdop': 100.0,
            'voltage': 0, 'current': 0, 'battery_remaining': 0,
            'armed': False, 'system_status': 0, 'mode': 'UNKNOWN',
            'error': "", 'dist_home': 0,
            'home_lat': None,
            'home_lon': None,
            'status_text': '',
            'ready_to_arm': False,
            'sensor_health': 0,
            'gps_string': 'No Fix',
            'ekf_velocity_var': 0.0,
            'ekf_pos_horiz_var': 0.0,
            'ekf_pos_vert_var': 0.0,
            'ekf_compass_var': 0.0,
            'ekf_flags': 0
        }
        
        # Payload State
        self.drop_index = 0 # 0 to 8
        self.lock = threading.Lock()
        self.thread = None


    def get_state(self):
        """Thread-safe access to state copy"""
        with self.lock:
            s = self.state.copy()
            s['connected'] = self.connected
            return s

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.master:
            try:
                self.master.close()
            except:
                pass
        self.connected = False
            
    def _update_loop(self):
        # Connection Attempt
        while self.running and not self.connected:
            try:
                print(f"{self.log_prefix} Connecting to {self.connect_str}...")
                self.master = mavutil.mavlink_connection(self.connect_str, baud=self.baud_rate)
                self.master.wait_heartbeat(timeout=3)
                print(f"{self.log_prefix} Heartbeat received from System {self.master.target_system}")
                self.connected = True
                
                # Request Data Streams (Modern)
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT, 1) # 1Hz
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 2) # 2Hz
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS, 1) # 1Hz
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 10) # 10Hz (Fast for smooth AHRS)
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT, 1) # 1Hz
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_EKF_STATUS_REPORT, 2) # 2Hz EKF
                
                # Request Data Streams (Legacy Fallback) - IMPORTANT for older SITL/Firmware
                try:
                    self.master.mav.request_data_stream_send(
                        self.master.target_system, self.master.target_component,
                        mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1
                    )
                except: pass
                
            except Exception as e:
                print(f"{self.log_prefix} Connection failed: {e}")
                time.sleep(2)
        
        # Main Loop
        while self.running:
            if not self.connected:
                time.sleep(1)
                continue
                
            try:
                # Send Heartbeat (GCS)
                self.master.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0
                )

                # Poll Pre-Arm Checks (Every 2 seconds approx)
                current_time = time.time()
                if current_time - self.last_prearm_poll > 2.0:
                    self.trigger_prearm_checks()
                    self.last_prearm_poll = current_time
                
                # Receive Messages
                while True:
                    msg = self.master.recv_match(blocking=False)
                    if not msg:
                        break
                    self._process_message(msg)
                    
                time.sleep(0.1) # 10Hz Loop
                
                # AGGRESSIVE DATA STREAM CHECK
                # If we haven't received Attitude for >2s, re-request EVERYTHING
                # This fixes the "Nothing Updating" issue on some flight controllers
                if time.time() - self.last_attitude_time > 2.0:
                     print(f"{self.log_prefix} Data Stalled. Re-requesting Streams...")
                     try:
                        self.master.mav.request_data_stream_send(
                            self.master.target_system, self.master.target_component,
                            mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1
                        )
                        # Also extra heartbeats
                        self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 10)
                     except: pass
                     self.last_attitude_time = time.time() # Reset to avoid spamming too fast

                
            except Exception as e:
                print(f"{self.log_prefix} Loop error: {e}")
                
    def _process_message(self, msg):
        type_ = msg.get_type()
        with self.lock:
            if type_ == 'HEARTBEAT':
                # Only process hearbeats from the target vehicle (usually system 1)
                new_mode = mavutil.mode_string_v10(msg)
                old_mode = self.state['mode']
                
                # Log mode changes
                if new_mode != old_mode and old_mode != 'UNKNOWN':
                    print(f"{self.log_prefix} 🔄 Mode: {new_mode}")
                
                self.state['mode'] = new_mode
                self.state['raw_mode_base'] = msg.base_mode
                self.state['raw_mode_custom'] = msg.custom_mode
                
                new_armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                if new_armed != self.state['armed']:
                    if new_armed:
                        print(f"{self.log_prefix} 🔴 ARMED")
                    else:
                        print(f"{self.log_prefix} 🟢 DISARMED")
                self.state['armed'] = new_armed
                self.state['system_status'] = msg.system_status
                
            elif type_ == 'GPS_RAW_INT':
                self.state['gps_fix'] = msg.fix_type
                self.state['gps_sats'] = msg.satellites_visible
                self.state['gps_hdop'] = msg.eph / 100.0
                
                # Fix String
                fixes = {0: "No Fix", 1: "No Fix", 2: "2D Fix", 3: "3D Fix", 4: "DGPS", 5: "RTK"}
                self.state['gps_string'] = fixes.get(msg.fix_type, f"Type {msg.fix_type}")
                
            elif type_ == 'GLOBAL_POSITION_INT':
                self.state['alt_rel'] = msg.relative_alt / 1000.0 # mm to m
                self.state['heading'] = msg.hdg / 100.0
                curr_lat = msg.lat / 1e7
                curr_lon = msg.lon / 1e7
                self.state['lat'] = curr_lat
                self.state['lon'] = curr_lon
                
                # Velocity & Climb
                vx = msg.vx / 100.0
                vy = msg.vy / 100.0
                vz = msg.vz / 100.0
                self.state['speed'] = (vx**2 + vy**2)**0.5
                self.state['climb'] = -vz # NED convention, z down is positive
                
                # Set Home if first 3D fix
                if self.state['gps_fix'] >= 3 and self.state['home_lat'] is None:
                    self.state['home_lat'] = curr_lat
                    self.state['home_lon'] = curr_lon
                    print(f"{self.log_prefix} Home Set: {curr_lat}, {curr_lon}")
                    
                # Calculate Dist
                if self.state['home_lat']:
                    self.state['dist_home'] = haversine(
                        self.state['home_lat'], self.state['home_lon'],
                        curr_lat, curr_lon
                    )
                
            elif type_ == 'SYS_STATUS':
                self.state['voltage'] = msg.voltage_battery / 1000.0
                # Capture Sensor Health Bitmap
                self.state['sensor_health'] = msg.onboard_control_sensors_health

            elif type_ == 'ATTITUDE':
                self.state['roll'] = msg.roll
                self.state['pitch'] = msg.pitch
                self.state['yaw'] = msg.yaw
                self.last_attitude_time = time.time() # Mark alive


            elif type_ == 'STATUSTEXT':
                # msg.text is bytes in newer pymavlink, sometimes string
                text = msg.text
                if hasattr(text, 'decode'):
                    text = text.decode('utf-8', errors='ignore')
                
                # Add emoji based on message type
                if "PreArm:" in text:
                    emoji = "⚠️"
                elif "Ready to fly" in text or "Arm" in text:
                    emoji = "✅"
                elif "Error" in text.lower() or "Fail" in text.lower():
                    emoji = "❌"
                elif "GPS" in text:
                    emoji = "🛰️"
                elif "Calibrat" in text:
                    emoji = "🔧"
                elif "Mode" in text or "mode" in text:
                    emoji = "🔄"
                else:
                    emoji = "📡"
                
                print(f"{self.log_prefix} {emoji} {text}")
                self.state['status_text'] = text
                
                # Simple Logic to detect Ready/Not Ready from ArduPilot Text
                # ArduPilot sends "PreArm: [Reason]" when checks fail
                # ArduPilot sends "Ready to fly" when checks pass
                if "PreArm:" in text:
                    self.state['ready_to_arm'] = False
                    self.state['error'] = text # Store specifically as error
                elif "Ready to fly" in text:
                    self.state['ready_to_arm'] = True
                    self.state['error'] = "" # Clear error
                elif "ARMED" in text:
                     # Sometimes text confirms arming
                     pass
                
            elif type_ == 'EKF_STATUS_REPORT':
                self.state['ekf_velocity_var'] = msg.velocity_variance
                self.state['ekf_pos_horiz_var'] = msg.pos_horiz_variance
                self.state['ekf_pos_vert_var'] = msg.pos_vert_variance
                self.state['ekf_compass_var'] = msg.compass_variance
                self.state['ekf_flags'] = msg.flags
                
    def _request_message_interval(self, message_id, frequency_hz):
        if not self.master: return
        interval_us = int(1000000 / frequency_hz)
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            message_id, interval_us, 0, 0, 0, 0, 0
        )

    # --- COMMANDS ---
    
    def set_mode(self, mode_name):
        if not self.master: return
        print(f"{self.log_prefix} Setting Mode: {mode_name}")
        mode_id = self.master.mode_mapping().get(mode_name)
        if mode_id is None:
            print(f"{self.log_prefix} Unknown mode: {mode_name}")
            return
        self.master.set_mode(mode_id)
        
    def arm_disarm(self, arm=True, force=False):
        if not self.master: return
        action = "ARM" if arm else "DISARM"
        
        # STRICT ARMING CHECKS (User Requirement - Mode Aware)
        if arm and not force:
            mode = self.state.get('mode', 'UNKNOWN')
            gps_modes = ['GUIDED', 'LOITER', 'AUTO', 'RTL', 'CIRCLE', 'POSHOLD']
            
            # Check 1: Explicit Error is ALWAYS a blocker
            err = self.state.get('error', '')
            if err:
                 print(f"{self.log_prefix} ❌ ABORT ARM: {err}")
                 return

            if mode in gps_modes:
                # STRICT GPS CHECKS
                if not self.state.get('ready_to_arm', False):
                     # If generic "not ready", and we are in GPS mode
                     print(f"{self.log_prefix} ❌ ABORT ARM: Waiting for 'Ready to Fly' in {mode}")
                     return
                
                hdop = self.state.get('gps_hdop', 99.9)
                if hdop >= 2.0:
                    print(f"{self.log_prefix} ❌ ABORT ARM: Poor GPS HDOP ({hdop:.1f}) required for {mode}")
                    return
            else:
                # STABILIZE / ALT_HOLD (Manual Modes)
                # Allow arming if no explicit error exists
                # We do NOT require "Ready to Fly" (which implies 3D Fix usually)
                pass
                
        print(f"{self.log_prefix} Sending {action} command (Force={force})")

        print(f"{self.log_prefix} Sending {action} command (Force={force})")
        force_val = 21196 if force else 0
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
            1 if arm else 0, force_val, 0, 0, 0, 0, 0
        )
        
    def takeoff(self, altitude=TAKEOFF_ALT_DEFAULT):
        if not self.master: return
        print(f"{self.log_prefix} Taking off to {altitude}m (Relative)")
        
        current_lat = int(self.state['lat'] * 1e7)
        current_lon = int(self.state['lon'] * 1e7)
        
        # Use COMMAND_INT for explicit frame support
        self.master.mav.command_int_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, # Frame: Relative to Home
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, # current, autocontinue
            0, 0, 0, 0, # params 1-4
            current_lat, # x (Lat)
            current_lon, # y (Lon)
            altitude     # z (Alt)
        )
        
    def send_velocity(self, vx, vy, vz=0):
        if not self.master: return
        # GUIDED Velocity Control (BODY FRAME causes drift when stopping!)
        # Use LOCAL_NED (Frame 1) for Earth-Relative Velocity (North/East/Down)
        # This ensures (0,0,0) means "Stop moving relative to the Ground" vs "Stop moving relative to nose".
        self.master.mav.set_position_target_local_ned_send(
            0, # time_boot_ms
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED, # CHANGED from BODY_OFFSET_NED (8) to LOCAL_NED (1)
            0b0000111111000111, # type_mask (only speeds enabled)
            0, 0, 0, # x, y, z positions
            vx, vy, vz, # x, y, z velocity in m/s
            0, 0, 0, # x, y, z acceleration
            0, 0 # yaw, yaw_rate
        )

    def set_home(self, lat=0, lon=0, alt=0, set_current=False):
        if not self.master: return
        
        if set_current:
            print(f"{self.log_prefix} Setting HOME to Current EKF Position")
            # param1=1: Use current position (ArduPilot spec)
            self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                mavutil.mavlink.MAV_CMD_DO_SET_HOME, 0,
                1, # 0=Use Current, 1=Use Specified? 
                   # Wait, MAV_CMD_DO_SET_HOME:
                   # Param1: 1=Use current, 0=Use specified (Standard) 
                   # Actually ArduPilot: 1=Use Current, 0=Use Supplied.
                0, 0, 0, 0, 0, 0
            )
            # We can't update internal state 'home_lat' accurately until we read it back.
        else:
            print(f"{self.log_prefix} Setting HOME to Specified: {lat}, {lon}, {alt}")
            self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                mavutil.mavlink.MAV_CMD_DO_SET_HOME, 0,
                0, # 0=Use Supplied
                0, 0, 0, 
                lat, lon, alt
            )
            self.state['home_lat'] = lat
            self.state['home_lon'] = lon

    def set_target_altitude(self, alt_m):
        """Change target altitude using MAV_CMD_DO_CHANGE_ALTITUDE or guided goto"""
        if not self.master: return
        print(f"{self.log_prefix} Setting target altitude to {alt_m}m")
        
        # Get current position
        s = self.get_state()
        lat = s['lat']
        lon = s['lon']
        
        if lat == 0 or lon == 0:
            print(f"{self.log_prefix} Cannot set altitude - no GPS position")
            return
        
        # Use SET_POSITION_TARGET_GLOBAL_INT for precise altitude control
        # This works in GUIDED mode
        self.master.mav.set_position_target_global_int_send(
            0,  # time_boot_ms
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000,  # type_mask (only position)
            int(lat * 1e7),  # lat_int
            int(lon * 1e7),  # lon_int
            alt_m,  # altitude
            0, 0, 0,  # velocity
            0, 0, 0,  # accel
            0, 0  # yaw, yaw_rate
        )
        
        # Also store it for reference
        self.target_altitude = alt_m
    
    def set_speed(self, speed_ms):
        """Set ground speed using MAV_CMD_DO_CHANGE_SPEED"""
        if not self.master: return
        print(f"{self.log_prefix} Setting speed to {speed_ms} m/s")
        
        # MAV_CMD_DO_CHANGE_SPEED
        # param1: Speed type (0=Airspeed, 1=Ground Speed)
        # param2: Speed (m/s)
        # param3: Throttle (-1=no change)
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED, 0,
            1,  # Ground speed
            speed_ms,  # Speed in m/s
            -1,  # Throttle (no change)
            0, 0, 0, 0
        )
        
        # Store for reference
        self.target_speed = speed_ms

    def reset_payloads(self):
        """Resets all 4 payload servos (Output 5-8) to 1000us"""
        if not self.master: return
        print(f"{self.log_prefix} [Backend] 🔄 Resetting All Payloads to 1000us")
        for servo_id in [5, 6, 7, 8]:
             self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                183, 0, servo_id, 1000, 0, 0, 0, 0, 0
            )
        self.drop_index = 0

    def drop_payload(self):
        """
        Sequential Drop Logic:
        8 Stages total.
        Servos: 5, 6, 7, 8 (Output 5-8)
        Stages per servo: 1500 (Drop 1), 2000 (Drop 2)
        """
        if not self.master: return
        
        if self.drop_index >= 8:
            # If user clicks again after completion, just ensure we are in RTL or Reset?
            # With the new logic below, this state shouldn't be reached often unless they click FAST.
            print(f"{self.log_prefix} [Backend] ⚠️ Sequence already complete. Ensuring RTL.")
            self.set_mode("RTL")
            return

        # Calculate Servo and PWM

        servo_map = [5, 6, 7, 8]
        servo_idx = self.drop_index // 2
        stage = self.drop_index % 2
        
        target_servo = servo_map[servo_idx]
        target_pwm = 1500 if stage == 0 else 2000
        
        print(f"{self.log_prefix} [Backend] 📦 Drop {self.drop_index+1}/8: Servo {target_servo} -> {target_pwm}us")
        
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            183, 0, target_servo, target_pwm, 0, 0, 0, 0, 0
        )
        
        self.drop_index += 1
        
        # Check for Sequence Completion (Auto-RTL)
        if self.drop_index >= 8:
            print(f"{self.log_prefix} [Backend] 🏁 All Payloads Dropped. Auto-Switching to RTL.")
            self.set_mode("RTL")
            # Optional: Delay reset or reset immediately?
            # We'll reset the index/servos instantly so they are ready for next flight
            # and don't stay strained open.
            self.reset_payloads()


    def smart_emergency_land(self):

        """
        Executes sequence: Stop -> Rise to 4m -> Hover 3s -> Land.
        Runs in a separate thread to not block GUI.
        """
        def _seq():
            if not self.master: return
            
            print(f"{self.log_prefix} 🚨 SMART EMERGENCY TRIGGERED 🚨")
            
            # 1. STOP & BRAKE
            self.set_mode("GUIDED")
            self.send_velocity(0, 0, 0)
            time.sleep(0.5)
            
            # 2. ASCEND TO 4M (Relative)
            print(f"{self.log_prefix} Ascending/Moving to 4m Altitude...")
            # We will use set_position_target_global_int to current lat/lon + 4m Rel Alt
            # First, need current location.
            # Fallback: Just send Takeoff to 4m if close to ground, or Change Alt.
            # MAV_CMD_CONDITION_CHANGE_ALT is useful.
            
            # Robust approach: Get current lat/lon from state, send goto.
            # For simplicity in this demo: Use takeoff command (works in air for ArduCopter to change alt).
            self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
                0, 0, 0, 0, 0, 0, 4.0 # 4 meters
            )
            
            # Wait for ascent (simulated wait)
            time.sleep(4) 
            
            # 3. HOVER 3 SECONDS
            print(f"{self.log_prefix} Hovering for 3 seconds...")
            self.send_velocity(0, 0, 0)
            time.sleep(3)
            
            # 4. LAND
            print(f"{self.log_prefix} Landing...")
            self.set_mode("LAND")

            
        threading.Thread(target=_seq, daemon=True).start()

    def trigger_prearm_checks(self):
        """
        Sends MAV_CMD_RUN_PREARM_CHECKS to force the FC to report any issues
        via STATUSTEXT.
        """
        if not self.master or self.state['armed']: return
        
        # MAV_CMD_RUN_PREARM_CHECKS = 401
        try:
            self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                401, # MAV_CMD_RUN_PREARM_CHECKS
                0,
                0, 0, 0, 0, 0, 0, 0
            )
        except Exception:
            pass

