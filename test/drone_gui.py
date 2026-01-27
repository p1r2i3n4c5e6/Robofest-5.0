#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
from pymavlink import mavutil
import threading
import time
import sys
import math
import tkintermapview # ADDED

# CONFIGURATION
DEFAULT_CONNECTION_STRING = '/dev/ttyUSB0'
DEFAULT_BAUD = 57600
TARGET_SYSTEM = 1
TARGET_COMPONENT = 1

# FAILSAFES
MIN_SATS = 5
MAX_HDOP = 2.0
MIN_FIX_TYPE = 3  # 3D Fix

# FLIGHT PARAMETERS
TAKEOFF_ALT = 5.0 # Meters
MOVE_SPEED = 2.0  # m/s for joystick

class DroneBackend:
    """
    Handles Mavlink communication in a separate thread.
    """
    def __init__(self, connect_str, baud_rate):
        self.connect_str = connect_str
        self.baud_rate = baud_rate
        self.master = None
        self.running = False
        self.connected = False
        
        # Vehicle State
        self.state = {
            'mode': 'UNKNOWN',
            'armed': False,
            'gps_fix': 0,
            'gps_sats': 0,
            'gps_hdop': 99.9,
            'alt_rel': 0.0,
            'heading': 0,
            'voltage': 0.0,
            'system_status': 0
        }
        self.lock = threading.Lock()
        
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.master:
            self.master.close()
            
    def _update_loop(self):
        # Connection Attempt
        while self.running and not self.connected:
            try:
                print(f"Connecting to {self.connect_str}...")
                self.master = mavutil.mavlink_connection(self.connect_str, baud=self.baud_rate)
                self.master.wait_heartbeat(timeout=3)
                print(f"Heartbeat received from System {self.master.target_system}")
                self.connected = True
                
                # Request Data Streams
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT, 1) # 1Hz
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 2) # 2Hz
                self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS, 1) # 1Hz
                
            except Exception as e:
                print(f"Connection failed: {e}")
                time.sleep(2)
        
        # Main Loop
        while self.running:
            if not self.connected:
                time.sleep(1)
                continue
                
            try:
                # Send Heartbeat
                self.master.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0
                )
                
                # Receive Messages
                while True:
                    msg = self.master.recv_match(blocking=False)
                    if not msg:
                        break
                        
                    self._process_message(msg)
                    
                time.sleep(0.1) # 10Hz Loop
                
            except Exception as e:
                print(f"Loop error: {e}")
                
    def _process_message(self, msg):
        type_ = msg.get_type()
        with self.lock:
            if type_ == 'HEARTBEAT':
                self.state['mode'] = mavutil.mode_string_v10(msg)
                self.state['armed'] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self.state['system_status'] = msg.system_status
                
            elif type_ == 'GPS_RAW_INT':
                self.state['gps_fix'] = msg.fix_type
                self.state['gps_sats'] = msg.satellites_visible
                self.state['gps_hdop'] = msg.eph / 100.0
                
            elif type_ == 'GLOBAL_POSITION_INT':
                self.state['alt_rel'] = msg.relative_alt / 1000.0 # mm to m
                self.state['heading'] = msg.hdg / 100.0
                
            elif type_ == 'SYS_STATUS':
                self.state['voltage'] = msg.voltage_battery / 1000.0
                
    def _request_message_interval(self, message_id, frequency_hz):
        interval_us = int(1000000 / frequency_hz)
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            message_id, interval_us, 0, 0, 0, 0, 0
        )

    # --- COMMANDS ---
    
    def set_mode(self, mode_name):
        if not self.master: return
        mode_id = self.master.mode_mapping()[mode_name]
        self.master.set_mode(mode_id)
        
    def arm_disarm(self, arm=True, force=False):
        if not self.master: return
        force_val = 21196 if force else 0
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
            1 if arm else 0, force_val, 0, 0, 0, 0, 0
        )
        
    def takeoff(self, altitude):
        if not self.master: return
        print(f"Taking off to {altitude}m (Relative)")
        
        # Use COMMAND_INT for explicit frame support
        self.master.mav.command_int_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, # Frame: Relative to Home
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, # current, autocontinue
            0, 0, 0, 0, # params 1-4
            int(self.state.get('lat', 0) * 1e7), # x (Lat) - Note: drone_gui might not have lat/lon in state yet
            int(self.state.get('lon', 0) * 1e7), # y (Lon)
            altitude     # z (Alt)
        )
        
    def send_velocity(self, vx, vy, vz=0):
        if not self.master: return
        
        # Check Mode for Routing
        mode = self.state['mode']
        
        if mode == 'LOITER':
            self.send_rc_override(vx, vy, vz)
            return

        # Default GUIDED Velocity Control
        # Velocity in BODY_OFFSET_NED frame
        # vx: Forward(+)/Back(-), vy: Right(+)/Left(-), vz: Down(+)/Up(-)
        self.master.mav.set_position_target_local_ned_send(
            0, # time_boot_ms
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            0b0000111111000111, # type_mask (only speeds enabled)
            0, 0, 0, # x, y, z positions (not used)
            vx, vy, vz, # x, y, z velocity in m/s
            0, 0, 0, # x, y, z acceleration (not used)
            0, 0 # yaw, yaw_rate (not used)
        )

    def upload_mission(self, waypoints, altitude):
        """
        Uploads a list of waypoints [(lat, lon), ...] as a mission.
        """
        if not self.master: return
        
        # 1. Clear existing mission
        self.master.mav.mission_clear_all_send(self.master.target_system, self.master.target_component)
        
        # 2. Send Mission Count
        count = len(waypoints) + 1 # +1 for Landing
        self.master.mav.mission_count_send(
            self.master.target_system, self.master.target_component,
            count,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )
        
        # 3. Send Mission Items
        for i, (lat, lon) in enumerate(waypoints):
            print(f"Uploading WP {i}: {lat}, {lon} at {altitude}m")
            self.master.mav.mission_item_int_send(
                self.master.target_system, self.master.target_component,
                i, # seq
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                0, 1, # current, autocontinue
                0, 0, 0, 0, # p1, p2, p3, p4
                int(lat * 1e7),
                int(lon * 1e7),
                int(altitude),
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )
            time.sleep(0.05) # Small buffer
            
        # 4. Add LAND command at the last waypoint
        if waypoints:
            last_lat, last_lon = waypoints[-1]
            print(f"Appending LAND at {last_lat}, {last_lon}")
            self.master.mav.mission_item_int_send(
                self.master.target_system, self.master.target_component,
                len(waypoints), # seq (next one)
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_LAND,
                0, 1, # current, autocontinue
                0, 0, 0, 0, # p1, p2, p3, p4
                int(last_lat * 1e7),
                int(last_lon * 1e7),
                0, # Altitude 0 for land
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )
            time.sleep(0.05)

    def send_rc_override(self, vx, vy, vz):
        """
        Map velocity vectors to RC PWM for Loiter control.
        Center: 1500. Range: +/- 200.
        """
        # Pitch (Ch2): Forward (+vx) -> Low PWM (ArduPilot standard: Low=Pitch Forward/Down)
        # Wait! ArduPilot Pitch: Low PWM (1100) = Nose Down = Forward. High (1900) = Nose Up = Back.
        pwm_pitch = 1500
        if vx > 0.1: pwm_pitch = 1300  # Forward
        elif vx < -0.1: pwm_pitch = 1700 # Backward

        # Roll (Ch1): Right (+vy) -> High PWM. Left (-vy) -> Low PWM.
        pwm_roll = 1500
        if vy > 0.1: pwm_roll = 1700   # Right
        elif vy < -0.1: pwm_roll = 1300  # Left

        # Throttle (Ch3): Up (-vz) -> High PWM. Down (+vz) -> Low PWM.
        pwm_throttle = 1500 # Center stick = Maintain Altitude in Loiter
        if vz < -0.1: pwm_throttle = 1700 # Up
        elif vz > 0.1: pwm_throttle = 1300  # Down

        # Yaw (Ch4): Unused (65535 to ignore, but we sent 0 before?)
        # 65535 = ignore. But if we want no yaw, we should send 1500? 
        # Safest is 65535 (let usage of real RC stick if present, or hold heading).
        
        self.master.mav.rc_channels_override_send(
            self.master.target_system, self.master.target_component,
            pwm_roll,      # Ch1: Roll
            pwm_pitch,     # Ch2: Pitch
            pwm_throttle,  # Ch3: Throttle
            65535,         # Ch4: Yaw (Ignore)
            0, 0, 0, 0     # Ch5-8: Unused
        )

class DroneGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Drone Command Center")
        self.root.title("Drone Command Center")
        self.root.geometry("1400x800") # Resized for Map
        
        self.backend = None
        self.is_connected = False
        self.waypoints = [] # List of (lat, lon)
        
        self.create_widgets()
        self.update_ui_loop()
        
    def create_widgets(self):
        # --- Connection Bar ---
        top_frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(top_frame, text="Device:").pack(side="left")
        self.entry_device = ttk.Entry(top_frame, width=20)
        self.entry_device.insert(0, DEFAULT_CONNECTION_STRING)
        self.entry_device.pack(side="left", padx=5)
        
        ttk.Label(top_frame, text="Baud:").pack(side="left")
        self.entry_baud = ttk.Entry(top_frame, width=10)
        self.entry_baud.insert(0, str(DEFAULT_BAUD))
        self.entry_baud.pack(side="left", padx=5)
        
        self.btn_connect = ttk.Button(top_frame, text="Connect", command=self.toggle_connection)
        self.btn_connect.pack(side="left", padx=10)
        
        # --- Main Layout ---
        # --- Main Layout ---
        # PanedWindow: Left (Map) | Right (Controls)
        main_pane = ttk.PanedWindow(self.root, orient="horizontal")
        main_pane.pack(fill="both", expand=True, padx=10, pady=5)
        
        # --- LEFT PANEL: MAP ---
        map_frame = ttk.Frame(main_pane)
        main_pane.add(map_frame, weight=3) # Give map more space
        
        # Map Widget
        self.map_widget = tkintermapview.TkinterMapView(map_frame, width=800, height=600, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22) # Google Satellite
        self.map_widget.set_position(35.363261, 138.730302) # Default Mt Fuji
        self.map_widget.set_zoom(15)
        
        # Map Events
        self.map_widget.add_right_click_menu_command(label="Add Waypoint Here", command=self.add_waypoint_click, pass_coords=True)
        self.map_widget.add_left_click_map_command(self.add_waypoint_click) # Click to add
        
        # --- RIGHT PANEL: CONTROLS ---
        right_pane = ttk.Frame(main_pane)
        main_pane.add(right_pane, weight=1)
        
        # Status
        self.status_frame = ttk.LabelFrame(right_pane, text="System Status", padding=10)
        self.status_frame.pack(fill="x", pady=5)
        
        self.lbl_status_con = self.create_status_label("Connection: Disconnected")
        self.lbl_status_mode = self.create_status_label("Mode: Unknown")
        self.lbl_status_arm = self.create_status_label("State: Disarmed")
        self.lbl_status_bat = self.create_status_label("Battery: 0.0V")
        
        ttk.Separator(self.status_frame, orient="horizontal").pack(fill="x", pady=5)
        
        gps_grid = ttk.Frame(self.status_frame)
        gps_grid.pack(fill="x")
        self.lbl_gps_fix = ttk.Label(gps_grid, text="Fix: No GPS", font=("Consolas", 10))
        self.lbl_gps_fix.grid(row=0, column=0, sticky="w")
        self.lbl_gps_sats = ttk.Label(gps_grid, text="Sats: 0", font=("Consolas", 10))
        self.lbl_gps_sats.grid(row=0, column=1, sticky="w", padx=10)
        self.lbl_gps_hdop = ttk.Label(gps_grid, text="HDOP: 99.9", font=("Consolas", 10))
        self.lbl_gps_hdop.grid(row=1, column=0, sticky="w")
        self.lbl_alt = ttk.Label(gps_grid, text="Alt: 0.0m", font=("Consolas", 10))
        self.lbl_alt.grid(row=1, column=1, sticky="w", padx=10)

        # Tabbed Control (Manual / Auto)
        control_tabs = ttk.Notebook(right_pane)
        control_tabs.pack(fill="both", expand=True, pady=10)
        
        # Tab 1: Manual
        tab_manual = ttk.Frame(control_tabs, padding=10)
        control_tabs.add(tab_manual, text="Manual Control")
        
        self.create_manual_controls(tab_manual)
        
        # Tab 2: Auto / Mission
        tab_auto = ttk.Frame(control_tabs, padding=10)
        control_tabs.add(tab_auto, text="Auto / Mission")
        
        self.create_auto_controls(tab_auto)
        
        # Log Output
        log_frame = ttk.LabelFrame(right_pane, text="Logs", padding=5)
        log_frame.pack(fill="both", expand=True, pady=5)
        
        self.txt_log = tk.Text(log_frame, height=8, font=("Consolas", 8))
        self.txt_log.pack(fill="both", expand=True)
        
        # Redirect stdout
        class Redirect():
            def __init__(self, widget):
                self.widget = widget
            def write(self, str):
                self.widget.insert("end", str)
                self.widget.see("end")
            def flush(self): pass
            
        sys.stdout = Redirect(self.txt_log)
        
    def create_manual_controls(self, parent):
        self.btn_arm = ttk.Button(parent, text="ARM", command=self.cmd_arm, state="disabled")
        self.btn_arm.pack(fill="x", pady=2)
        
        self.btn_disarm = ttk.Button(parent, text="DISARM", command=self.cmd_disarm, state="disabled")
        self.btn_disarm.pack(fill="x", pady=2)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        
        alt_frame = ttk.Frame(parent)
        alt_frame.pack(fill="x", pady=2)
        ttk.Label(alt_frame, text="Alt (m):").pack(side="left")
        self.entry_takeoff_alt = ttk.Entry(alt_frame, width=5)
        self.entry_takeoff_alt.insert(0, str(TAKEOFF_ALT))
        self.entry_takeoff_alt.pack(side="right", expand=True, fill="x")

        self.btn_takeoff = ttk.Button(parent, text="TAKEOFF", command=self.cmd_takeoff, state="disabled")
        self.btn_takeoff.pack(fill="x", pady=2)
        
        self.btn_land = ttk.Button(parent, text="LAND", command=self.cmd_land, state="disabled")
        self.btn_land.pack(fill="x", pady=2)
        
        self.btn_guided = ttk.Button(parent, text="Mode: GUIDED", command=lambda: self.cmd_mode('GUIDED'), state="disabled")
        self.btn_guided.pack(fill="x", pady=2)

        self.btn_loiter = ttk.Button(parent, text="Mode: LOITER", command=lambda: self.cmd_mode('LOITER'), state="disabled")
        self.btn_loiter.pack(fill="x", pady=2)
        
        self.btn_stop = ttk.Button(parent, text="EMERGENCY STOP", command=self.cmd_estop, style="Danger.TButton")
        self.btn_stop.pack(fill="x", pady=5)

        # Joystick Panel
        joy_frame = ttk.LabelFrame(parent, text="Directional Control", padding=10)
        joy_frame.pack(fill="both", expand=True, pady=5)
        
        joy_grid = ttk.Frame(joy_frame)
        joy_grid.pack(expand=True)
        
        self.btn_j_fwd = ttk.Button(joy_grid, text="▲")
        self.btn_j_fwd.grid(row=0, column=1, padx=2, pady=2)
        self.bind_joy_btn(self.btn_j_fwd, MOVE_SPEED, 0, 0)
        
        self.btn_j_left = ttk.Button(joy_grid, text="◀")
        self.btn_j_left.grid(row=1, column=0, padx=2, pady=2)
        self.bind_joy_btn(self.btn_j_left, 0, -MOVE_SPEED, 0)

        self.btn_j_right = ttk.Button(joy_grid, text="▶")
        self.btn_j_right.grid(row=1, column=2, padx=2, pady=2)
        self.bind_joy_btn(self.btn_j_right, 0, MOVE_SPEED, 0)
        
        self.btn_j_back = ttk.Button(joy_grid, text="▼")
        self.btn_j_back.grid(row=2, column=1, padx=2, pady=2)
        self.bind_joy_btn(self.btn_j_back, -MOVE_SPEED, 0, 0)

        # Vertical Controls
        vert_frame = ttk.Frame(joy_grid)
        vert_frame.grid(row=0, column=4, rowspan=3, padx=20)
        
        ttk.Label(vert_frame, text="Vertical").pack()
        
        self.btn_up = ttk.Button(vert_frame, text="UP ⇧")
        self.btn_up.pack(pady=5)
        self.bind_joy_btn(self.btn_up, 0, 0, -MOVE_SPEED) # NED: Up is negative Z

        self.btn_down = ttk.Button(vert_frame, text="DOWN ⇩")
        self.btn_down.pack(pady=5)
        self.bind_joy_btn(self.btn_down, 0, 0, MOVE_SPEED) # NED: Down is positive Z
        
    def create_auto_controls(self, parent):
        ttk.Label(parent, text="Waypoints:").pack(anchor="w")
        self.lst_waypoints = tk.Listbox(parent, height=10)
        self.lst_waypoints.pack(fill="x", pady=5)
        
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x")
        
        ttk.Button(btn_frame, text="Clear", command=self.clear_waypoints).pack(side="left", expand=True, fill="x")
        ttk.Button(btn_frame, text="Upload", command=self.upload_mission).pack(side="left", expand=True, fill="x")
        
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        
        self.btn_auto = ttk.Button(parent, text="START MISSION (AUTO)", command=lambda: self.cmd_mode('AUTO'), state="disabled")
        self.btn_auto.pack(fill="x", pady=5)
        
        ttk.Label(parent, text="Click on Map to add waypoints.", font=("Arial", 8, "italic"), wraplength=150).pack(pady=10)

    def add_waypoint_click(self, coords):
        # coords is (lat, lon)
        lat, lon = coords
        print(f"Added WP: {lat:.6f}, {lon:.6f}")
        
        self.waypoints.append((lat, lon))
        
        # Update Listbox
        self.lst_waypoints.insert("end", f"{len(self.waypoints)}: {lat:.6f}, {lon:.6f}")
        
        # Update Map
        # Add Marker
        self.map_widget.set_marker(lat, lon, text=str(len(self.waypoints)))
        
        # Draw Path
        if len(self.waypoints) > 1:
             self.map_widget.set_path(self.waypoints)

    def clear_waypoints(self):
        self.waypoints = []
        self.lst_waypoints.delete(0, "end")
        self.map_widget.delete_all_marker()
        self.map_widget.delete_all_path()
        print("Waypoints cleared.")

    def upload_mission(self):
        if not self.backend or not self.backend.connected:
            messagebox.showerror("Error", "Not Connected")
            return
            
        if not self.waypoints:
            messagebox.showerror("Error", "No waypoints to upload")
            return
            
        try:
            alt = float(self.entry_takeoff_alt.get())
        except ValueError:
            alt = TAKEOFF_ALT
            
        self.backend.upload_mission(self.waypoints, alt)
        messagebox.showinfo("Success", f"Mission Uploaded ({len(self.waypoints)} items at {alt}m)")

        # Styles
        style = ttk.Style()
        style.configure("Danger.TButton", foreground="red")

    def create_status_label(self, text):
        lbl = ttk.Label(self.status_frame, text=text, font=("Consolas", 10))
        lbl.pack(anchor="w", pady=2)
        return lbl
        
    def bind_joy_btn(self, btn, vx, vy, vz):
        # Using bind for Press and Release events
        btn.bind('<ButtonPress-1>', lambda e: self.start_moving(vx, vy, vz))
        btn.bind('<ButtonRelease-1>', lambda e: self.stop_moving())

    def start_moving(self, vx, vy, vz):
        self.move_vector = (vx, vy, vz)
        self.moving = True
        self._move_loop()
        
    def stop_moving(self):
        self.moving = False
        self.move_vector = (0,0,0)
        # Send one stop command
        if self.backend:
            self.backend.send_velocity(0, 0, 0)
            
    def _move_loop(self):
        if self.moving and self.backend:
            vx, vy, vz = self.move_vector
            self.backend.send_velocity(vx, vy, vz)
            self.root.after(100, self._move_loop) # Send at 10Hz

    # --- Actions ---
    
    def toggle_connection(self):
        if not self.is_connected:
            dev = self.entry_device.get()
            try:
                baud = int(self.entry_baud.get())
            except ValueError:
                messagebox.showerror("Error", "Baud rate must be an integer")
                return
                
            self.backend = DroneBackend(dev, baud)
            self.backend.start()
            self.is_connected = True
            self.btn_connect.config(text="Disconnect")
            self.entry_device.config(state="disabled")
            self.entry_baud.config(state="disabled")
        else:
            if self.backend:
                self.backend.stop()
            self.is_connected = False
            self.btn_connect.config(text="Connect")
            self.entry_device.config(state="normal")
            self.entry_baud.config(state="normal")
            self.reset_ui()
            
    def cmd_arm(self):
        # SAFETY CHECK
        state = self.backend.state
        if state['gps_fix'] < MIN_FIX_TYPE:
            messagebox.showerror("Safety Error", f"GPS Fix ({state['gps_fix']}) < 3D")
            return
        if state['gps_sats'] < MIN_SATS:
            messagebox.showerror("Safety Error", f"Satellites ({state['gps_sats']}) < {MIN_SATS}")
            return
        if state['gps_hdop'] > MAX_HDOP:
            messagebox.showerror("Safety Error", f"HDOP ({state['gps_hdop']:.2f}) > {MAX_HDOP}")
            return
            
        self.backend.arm_disarm(True)
        
    def cmd_disarm(self):
        if messagebox.askyesno("Confirm", "Disarm vehicle?"):
            self.backend.arm_disarm(False, force=False)
            
    def cmd_takeoff(self):
        # 1. Get Altitude
        try:
            alt = float(self.entry_takeoff_alt.get())
            if alt <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Invalid Takeoff Altitude")
            return

        # 2. Verify Armed (User requested strict separation)
        if not self.backend.state['armed']:
            messagebox.showerror("Procedure Error", "Vehicle must be ARMED before Takeoff.\nPlease press ARM.")
            return

        # 3. Verify Guided Mode
        if "GUIDED" not in self.backend.state['mode']:
             if messagebox.askyesno("Mode Mismatch", "Vehicle not in GUIDED mode. Switch to GUIDED?"):
                 self.backend.set_mode("GUIDED")
                 time.sleep(0.5)
             else:
                 return
                 
        self.backend.takeoff(alt)
        
    def cmd_land(self):
        self.backend.set_mode("LAND")
        
    def cmd_mode(self, mode):
        self.backend.set_mode(mode)
        
    def cmd_estop(self):
        # Immediate disarm - FORCE
        print("EMERGENCY STOP TRIGGERED")
        self.backend.arm_disarm(False, force=True)

    def reset_ui(self):
        self.lbl_status_con.config(text="Connection: Disconnected", foreground="red")
        self.set_buttons_state("disabled")
        
    def set_buttons_state(self, state):
        for btn in [self.btn_arm, self.btn_disarm, self.btn_takeoff, self.btn_land, 
                    self.btn_guided, self.btn_loiter, self.btn_auto]: # Added btn_auto
            btn.config(state=state)
            
    def update_ui_loop(self):
        if self.is_connected and self.backend:
            # Poll backend status
            state = self.backend.state
            
            # Connection
            if self.backend.connected:
                self.lbl_status_con.config(text="Connection: CONNECTED", foreground="green")
                self.set_buttons_state("normal")
            else:
                self.lbl_status_con.config(text="Connection: Connecting...", foreground="orange")
                
            with self.backend.lock:
                # Mode
                self.lbl_status_mode.config(text=f"Mode: {state['mode']}")
                
                # Armed
                arm_text = "ARMED" if state['armed'] else "DISARMED"
                arm_color = "red" if state['armed'] else "green" 
                self.lbl_status_arm.config(text=f"State: {arm_text}", foreground=arm_color)
                
                # Battery
                self.lbl_status_bat.config(text=f"Battery: {state['voltage']:.1f}V")
                
                # GPS
                fix_strs = {0:'No GPS', 1:'No Fix', 2:'2D', 3:'3D', 4:'DGPS', 5:'RTK Float', 6:'RTK Fix'}
                fix_str = fix_strs.get(state['gps_fix'], f"Type {state['gps_fix']}")
                self.lbl_gps_fix.config(text=f"Fix: {fix_str}")
                
                # GPS Safety Colors
                hdop_col = "green" if state['gps_hdop'] <= MAX_HDOP else "red"
                sat_col = "green" if state['gps_sats'] >= MIN_SATS else "red"
                
                self.lbl_gps_hdop.config(text=f"HDOP: {state['gps_hdop']:.2f}", foreground=hdop_col)
                self.lbl_gps_sats.config(text=f"Sats: {state['gps_sats']}", foreground=sat_col)
                
                self.lbl_alt.config(text=f"Alt: {state['alt_rel']:.1f}m")
                
        self.root.after(100, self.update_ui_loop)

if __name__ == "__main__":
    root = tk.Tk()
    app = DroneGUI(root)
    root.mainloop()
