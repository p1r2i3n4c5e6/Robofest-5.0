import math

class GeoTagger:
    def __init__(self, camera_fov_h_deg=62.2, camera_fov_v_deg=48.8, pitch_offset_deg=-90.0):
        """
        Initializes the geotagger with camera characteristics.
        :param camera_fov_h_deg: Horizontal Field of View (degrees). Default is approx for standard webcams/Pi CAM V2.
        :param camera_fov_v_deg: Vertical Field of View (degrees).
        :param pitch_offset_deg: Camera mounting angle relative to drone forward.
                                 -90 = Pointing straight down (Nadir)
                                  0 = Pointing straight forward
        """
        self.camera_fov_h_deg = camera_fov_h_deg
        self.camera_fov_v_deg = camera_fov_v_deg
        self.pitch_offset_deg = pitch_offset_deg

        # Earth radius in meters
        self.R_EARTH = 6378137.0

    def calculate_target_gps(self, drone_lat, drone_lon, drone_alt_m, 
                             drone_heading_deg, drone_pitch_deg, drone_roll_deg,
                             pixel_x, pixel_y, frame_w, frame_h):
        """
        Projects a pixel coordinate to a global GPS coordinate using flat-earth projection
        (suitable for drones flying < 120m altitude).

        Returns: (target_lat, target_lon) or (None, None) if math fails (e.g. looking at sky)
        """
        # 🛡️ SAFETY FIX: Allow low/negative alt for testing (drift). 
        # Clamp to 0.1m minimum for projection math to avoid division errors.
        safe_alt = max(0.1, drone_alt_m)

        # 1. Normalize pixel coordinates to range [-1.0, 1.0] (Center = 0,0)
        # Assuming origin (0,0) is top-left in OpenCV
        nx = (pixel_x - (frame_w / 2.0)) / (frame_w / 2.0)
        ny = ((frame_h / 2.0) - pixel_y) / (frame_h / 2.0)  # Invert Y so up is positive

        # 2. Convert normalized pixels to ray angles relative to camera lens center
        ray_angle_x_deg = nx * (self.camera_fov_h_deg / 2.0)
        ray_angle_y_deg = ny * (self.camera_fov_v_deg / 2.0)

        # 3. Apply Camera Pitch Offset & Drone Attitude
        # 
        # Drone Pitch: Positive means nose UP. 
        # Total pitch of the ray = Camera Mount Offset + Drone Pitch + Ray Y-angle
        
        # Example: Camera is strictly Nadir (-90). Drone pitches Nose Down (-10). Ray is center (0).
        # Total pitch = -90 + -10 + 0 = -100 deg. (Looking slightly behind the drone relative to nadir)
        # Since we use 0 = Horizon, -90 = Straight down.
        
        total_ray_pitch_deg = self.pitch_offset_deg + drone_pitch_deg + ray_angle_y_deg
        
        # If the ray is pointing at or above the horizon, we can't project it to the ground.
        if total_ray_pitch_deg >= 0:
             return None, None

        # Absolute ground projection angle (positive down from horizon)
        look_down_angle_deg = abs(total_ray_pitch_deg)
        look_down_angle_rad = math.radians(look_down_angle_deg)

        # 4. Calculate Forward Ground Distance (Length of purely forward/backward projection)
        # Using simple trigonometry: tan(angle) = Opposite(Altitude) / Adjacent(Distance)
        # So: Distance = Altitude / tan(angle)
        ground_distance_forward = safe_alt / math.tan(look_down_angle_rad)

        # 5. Calculate Lateral Ground Distance (Effect of Roll and Ray X-angle)
        # Note: True gimbal kinematics are more complex via rotation matrices,
        # but for small roll angles and small FOV, simple trig is accurate enough.
        # Total lateral angle = Drone Roll + Ray X-angle (Roll: positive means right wing down)
        total_ray_roll_deg = drone_roll_deg + ray_angle_x_deg
        
        # Lateral distance is perpendicular to forward distance vector.
        # Direct line-of-sight distance from camera to the forward target point on ground:
        los_distance = safe_alt / math.sin(look_down_angle_rad)
        ground_distance_lateral = los_distance * math.tan(math.radians(total_ray_roll_deg))

        # 6. Combine Forward/Lateral into a Single Distance and Bearing Offset
        # Pythagoras for total ground distance from directly plumb beneath drone
        total_ground_distance = math.sqrt(ground_distance_forward**2 + ground_distance_lateral**2)
        
        # Angle offset from drone's current heading
        bearing_offset_rad = math.atan2(ground_distance_lateral, ground_distance_forward)
        bearing_offset_deg = math.degrees(bearing_offset_rad)
        
        # True bearing to target (Wrap to 0-360)
        true_bearing_deg = (drone_heading_deg + bearing_offset_deg) % 360
        true_bearing_rad = math.radians(true_bearing_deg)

        # 7. Haversine Projection (Geodesic Offset calculation)
        # Calculate new lat/lon given a starting lat/lon, distance, and bearing.
        start_lat_rad = math.radians(drone_lat)
        start_lon_rad = math.radians(drone_lon)
        angular_distance = total_ground_distance / self.R_EARTH

        target_lat_rad = math.asin(math.sin(start_lat_rad) * math.cos(angular_distance) +
                                   math.cos(start_lat_rad) * math.sin(angular_distance) * math.cos(true_bearing_rad))
        
        target_lon_rad = start_lon_rad + math.atan2(math.sin(true_bearing_rad) * math.sin(angular_distance) * math.cos(start_lat_rad),
                                                    math.cos(angular_distance) - math.sin(start_lat_rad) * math.sin(target_lat_rad))

        target_lat = math.degrees(target_lat_rad)
        target_lon = math.degrees(target_lon_rad)

        return target_lat, target_lon

if __name__ == "__main__":
    # Test Sanity Check
    tagger = GeoTagger(camera_fov_h_deg=60.0, camera_fov_v_deg=45.0, pitch_offset_deg=-90.0) # Downward facing
    
    # Drone exactly at equator
    drone_lat = 0.0
    drone_lon = 0.0
    drone_alt = 10.0 # 10 meters up
    drone_heading = 0.0 # Facing North
    drone_pitch = 0.0 # Level
    drone_roll = 0.0 # Level
    
    # Target in center of camera (Should be straight down, so same lat/lon)
    lat, lon = tagger.calculate_target_gps(drone_lat, drone_lon, drone_alt, drone_heading, drone_pitch, drone_roll,
                                           pixel_x=640/2, pixel_y=480/2, frame_w=640, frame_h=480)
    print(f"Center Target Distance: {tagger.R_EARTH * math.radians(lat)} m N, {tagger.R_EARTH * math.radians(lon)} m E")
    
    # Target at top-center of camera (Forward in camera view. With Nadir cam, 'Up' in image is 'Forward' on ground)
    lat, lon = tagger.calculate_target_gps(drone_lat, drone_lon, drone_alt, drone_heading, drone_pitch, drone_roll,
                                           pixel_x=640/2, pixel_y=0, frame_w=640, frame_h=480)
    print(f"Top-Center Target Dist: {tagger.R_EARTH * math.radians(lat):.2f} m N, {tagger.R_EARTH * math.radians(lon):.2f} m E")
