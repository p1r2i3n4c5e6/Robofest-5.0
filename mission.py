import time
from pymavlink import mavutil

class MissionManager:
    """
    Handles Mission creation and upload.
    """
    def __init__(self, backend):
        self.backend = backend
        self.waypoints = [] # List of (lat, lon)

    def add_waypoint(self, lat, lon):
        self.waypoints.append((lat, lon))
        
    def remove_waypoint(self, index):
        if 0 <= index < len(self.waypoints):
            self.waypoints.pop(index)
        
    def clear_waypoints(self):
        self.waypoints = []

    def edit_waypoint(self, index, lat, lon):
        if 0 <= index < len(self.waypoints):
            self.waypoints[index] = (lat, lon)
        
    def upload_mission(self, altitude=5.0):
        if not self.backend.master:
            print(f"{self.backend.log_prefix} [Mission] Backend not connected.")
            return False

            
        if not self.waypoints:
            print(f"{self.backend.log_prefix} [Mission] No waypoints.")
            return False
            
        print(f"{self.backend.log_prefix} [Mission] Uploading {len(self.waypoints)} waypoints + TAKEOFF + LAND...")

        
        # 1. Clear existing mission
        self.backend.master.mav.mission_clear_all_send(
            self.backend.master.target_system, 
            self.backend.master.target_component
        )
        
        # 2. Count = 1 (Takeoff) + Waypoints + 1 (Land)
        count = len(self.waypoints) + 2
        self.backend.master.mav.mission_count_send(
            self.backend.master.target_system, 
            self.backend.master.target_component,
            count,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )
        
        # 3. Send Takeoff (Seq 0)
        # Using Relative Alt for Takeoff
        current_lat = int(self.backend.state['lat'] * 1e7)
        current_lon = int(self.backend.state['lon'] * 1e7)
        
        print(f"{self.backend.log_prefix} [Mission] Sending TAKEOFF to {altitude}m")
        self.backend.master.mav.mission_item_int_send(

            self.backend.master.target_system, 
            self.backend.master.target_component,
            0, # Seq 0
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 1, # current, autocontinue
            0, 0, 0, 0,
            current_lat, # Current Lat
            current_lon, # Current Lon
            int(altitude),
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )
        time.sleep(0.05)

        # 4. Send Waypoints (Seq 1..N)
        for i, (lat, lon) in enumerate(self.waypoints):
            seq = i + 1
            print(f"{self.backend.log_prefix} [Mission] Sending WP {seq}: {lat}, {lon}")
            self.backend.master.mav.mission_item_int_send(

                self.backend.master.target_system, 
                self.backend.master.target_component,
                seq, 
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                0, 1, 
                0, 0, 0, 0,
                int(lat * 1e7),
                int(lon * 1e7),
                int(altitude), # Maintain mission altitude
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )
            time.sleep(0.05)
            
        # 5. Send Land (Seq N+1)
        seq_land = len(self.waypoints) + 1
        print(f"{self.backend.log_prefix} [Mission] Sending LAND item at seq {seq_land}")
        last_lat, last_lon = self.waypoints[-1]

        self.backend.master.mav.mission_item_int_send(
            self.backend.master.target_system, 
            self.backend.master.target_component,
            seq_land, 
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            mavutil.mavlink.MAV_CMD_NAV_LAND,
            0, 1,
            0, 0, 0, 0,
            int(last_lat * 1e7),
            int(last_lon * 1e7),
            0, 
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )
        
    # --- GUIDED MODE EXECUTION ---
    
    def execute_guided_mission(self, altitude=5.0):
        """
        Executes the mission using GUIDED mode commands in a separate thread.
        Moves to each waypoint sequentially.
        """
        # --- PRE-FLIGHT CHECKS ---
        if not self.backend.master:
            print("[Mission] ❌ Backend not connected.")
            return

        if not self.waypoints:
            print("[Mission] ❌ No waypoints loaded.")
            return
            
        # GPS Check
        if self.backend.state['gps_fix'] < 3:
            print("[Mission] ❌ GPS Fix too low (Need 3D Fix). Aborting.")
            return
            
        # Home Check
        if not self.backend.state['home_lat']:
             print("[Mission] ❌ Home position not set. Aborting.")
             return

        import threading
        t = threading.Thread(target=self._run_guided_mission, args=(altitude,), daemon=True)
        t.start()
        
    def _run_guided_mission(self, altitude):
        try:
            print(f"{self.backend.log_prefix} [Mission] ▶️ STARTING MISSION with {len(self.waypoints)} Waypoints")

            
            # 1. Set Mode GUIDED
            print(f"{self.backend.log_prefix} [Mission] Switching to GUIDED...")
            self.backend.set_mode("GUIDED")

            
            # Verify Mode Change
            timeout = time.time() + 5
            while time.time() < timeout:
                 if self.backend.state['mode'] == 'GUIDED':
                     break
                 time.sleep(0.2)
                 
            if self.backend.state['mode'] != 'GUIDED':
                 print("[Mission] ❌ Failed to enter GUIDED mode. Aborting.")
                 return

            # 2. Arm & Takeoff Logic
            # (Removed dangerous set_home call)
            
            current_alt = self.backend.state['alt_rel']
            is_flying = current_alt > 2.0 and self.backend.state['armed']
            
            if is_flying:
                print(f"[Mission] ✈️ Already flying at {current_alt:.1f}m. Skipping Takeoff.")
            else:
                # Need to ARM and TAKEOFF
                if not self.backend.state['armed']:
                    print("[Mission] 🛡️ Arming...")
                    self.backend.arm_disarm(True)
                    
                    # Wait for Arming confirmation
                    t_arm = time.time() + 10
                    while not self.backend.state['armed'] and time.time() < t_arm:
                        time.sleep(0.5)
                        
                    if not self.backend.state['armed']:
                         print("[Mission] ❌ Arming failed. Aborting.")
                         return
                    
                    time.sleep(2) # Spool up time
                    
                print(f"[Mission] 🛫 Taking off to {altitude}m...")
                self.backend.takeoff(altitude)
                
                # Wait for Takeoff Climb
                time.sleep(5)
                # Timeout for climb to prevent infinite loop
                t_climb = time.time() + 20
                while self.backend.state['alt_rel'] < altitude * 0.90:
                     if time.time() > t_climb:
                          print("[Mission] ⚠️ Takeoff timeout (altitude not reached).")
                          break
                     print(f"[Mission] Climbing... {self.backend.state['alt_rel']:.1f}m")
                     time.sleep(1)
                print("[Mission] Takeoff Complete.")
            
            # 3. Iterate Waypoints
            self.paused = False
            self.resumed_flag = False
            
            last_stop_sent = 0
            last_goto_sent = 0
            
            for i, (lat, lon) in enumerate(self.waypoints):
                print(f"[Mission] 📍 Heading to WP {i+1}/{len(self.waypoints)}...")
                
                # Send Go To Command
                self._send_goto(lat, lon, altitude)
                
                # Wait for Arrival
                while True:
                    # PAUSE LOGIC
                    if self.paused:
                        # Keep sending 0 velocity to hold position in GUIDED
                        if time.time() - last_stop_sent > 1.0: # Send every 1s to keep link active
                             self.backend.send_velocity(0, 0, 0)
                             last_stop_sent = time.time()
                             # Debug log occasionally
                             # print(f"[Mission] DEBUG: Paused... Mode={self.backend.state['mode']}")
                        time.sleep(0.1)
                        continue
                    
                    # RESUME LOGIC (Explicit check)
                    if self.resumed_flag:
                        print(f"[Mission] ⚠️ DEBUG: Detected RESUME flag. Mode={self.backend.state['mode']}")
                        
                        # 1. Force GUIDED mode again to be safe
                        if self.backend.state['mode'] != 'GUIDED':
                             print("[Mission] Restoring GUIDED mode for resume...")
                             self.backend.set_mode("GUIDED")
                             time.sleep(0.2)
                        
                        # 2. Resend Target (Multiple times to ensure receipt)
                        print(f"[Mission] ▶️ Resuming to WP {i+1} : {lat}, {lon}")
                        for _ in range(3):
                            self._send_goto(lat, lon, altitude)
                            time.sleep(0.1)
                            
                        self.resumed_flag = False # Clear flag
                        last_goto_sent = time.time() # Reset timer
                        # Continue explicitly to skip the maintain logic this cycle
                        continue

                    # MAINTAIN TARGET LOGIC
                    # We resend the target every 2 seconds to ensure:
                    # 1. Packet loss doesn't stop the mission
                    # 2. Mode switches are enforced
                    
                    if time.time() - last_goto_sent > 2.0:
                        # print(f"[Mission] DEBUG: Maintaining WP {i+1}...")
                        self._send_goto(lat, lon, altitude)
                        last_goto_sent = time.time()
                    
                    curr_lat = self.backend.state['lat']
                    curr_lon = self.backend.state['lon']
                    dist = self._haversine(curr_lat, curr_lon, lat, lon)
                    
                    if dist < 2.0: # Reached within 2 meters
                        print(f"[Mission] ✅ Arrived at WP {i+1}")
                        break
                        
                    # Faster Loop for Instant Response
                    # Instead of huge 1s sleep, we sleep 0.1s x 5 times and check pause
                    for _ in range(5):
                        if self.paused or self.resumed_flag: break
                        time.sleep(0.1)
        except Exception as e:
            import traceback
            print(f"[Mission] 💥 THREAD CRASH: {e}")
            traceback.print_exc()

    def pause_mission(self):
        print(f"{self.backend.log_prefix} [Mission] ⏸️ BREAKING (Holding in GUIDED)...")
        # Send Stop Command (Velocity 0) - INSTANTLY
        self.backend.set_mode("GUIDED") # Ensure Mode
        for _ in range(3): # Spam a few times to ensure receipt
             self.backend.send_velocity(0, 0, 0)
             time.sleep(0.05)
        self.paused = True


        
    def resume_mission(self):
        print(f"{self.backend.log_prefix} [Mission] ▶️ RESUMING Mission (Switching to GUIDED)")
        self.backend.set_mode("GUIDED")
        self.paused = False
        self.resumed_flag = True

    def drop_payload(self):
        print(f"{self.backend.log_prefix} [Mission] 📦 Triggering Sequential Drop (Output 5-8)...")
        self.backend.drop_payload() 




                
        # 4. Mission End Behavior
        # Drone 1 (ID 2): Auto-RTL
        # Drone 0 (ID 1): Hover (for Drop Workflow)
        
        if self.backend.drone_id == 2:
             print(f"{self.backend.log_prefix} [Mission] 🏁 Mission Complete. Auto-RTL (Drone 1).")
             self.backend.set_mode("RTL")
        else:
             print(f"{self.backend.log_prefix} [Mission] 🏁 Mission Complete. Hovering at final waypoint.")



    def _send_goto(self, lat, lon, alt):
        # MAV_CMD_DO_REPOSITION or SET_POSITION_TARGET_GLOBAL_INT
        # We use SET_POSITION_TARGET_GLOBAL_INT for Guided
        if not self.backend.master: return
        
        self.backend.master.mav.set_position_target_global_int_send(
            0, # time_boot_ms
            self.backend.master.target_system,
            self.backend.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000, # type_mask (only pos enabled)
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
            0, 0, 0, # velocities
            0, 0, 0, # accel
            0, 0 # yaw
        )

    def _haversine(self, lat1, lon1, lat2, lon2):
        import math
        R = 6371000 # meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
