import tkinter as tk
from tkinter import ttk, messagebox, Listbox, Scrollbar
import tkintermapview
from PIL import Image, ImageTk
import time
import json
import urllib.request
import threading
import queue
import datetime
import sys

# Monkey-patch PIL.ImageTk to avoid __del__ errors
try:
    from PIL import ImageTk
    def _new_del(self):
        try:
            name = self.__photo.name
            self.__photo.tk.call("image", "delete", name)
        except (AttributeError, Exception):
            pass
    ImageTk.PhotoImage.__del__ = _new_del
except:
    pass


# --- THEME COLORS (Tactical Swarm) ---
BG_COLOR = "#050505"       # Deep Black
SIDEBAR_COLOR = "#111111"  # Dark Grey (almost black)
TEXT_COLOR = "#FFFFFF"     # White (Main Text)
TEXT_ACCENT = "#00AAFF"    # Electric Blue
BTN_SUCCESS = "#00FF00"    # Neon Green
BTN_DANGER = "#FF0000"     # Pure Red
BTN_ACTION = "#00AAFF"     # Electric Blue
BTN_WARN = "#FF6600"       # Safety Orange
NUM_DRONES = 4             # Configurable Swarm Size

import math

class AHRSWidget(tk.Canvas):
    def __init__(self, master, width=300, height=200):
        super().__init__(master, width=width, height=height, bg=BG_COLOR, highlightthickness=0)
        self.width = width
        self.height = height
        self.center_x = width / 2
        self.center_y = height / 2
        
        # Horizon Colors (Retro Terminal + User Request)
        self.sky_color = "#001a33"   # Deep "Transparent-like" Blue
        self.ground_color = "#003300" # Very dark green ("Transparent-like" Green)
        self.line_color = "#00ff00"
        
        # Bind Resize
        self.bind("<Configure>", self.on_resize)
        
        # Draw Initial State
        self.draw_horizon(0, 0)
        
    def on_resize(self, event):
        self.width = event.width
        self.height = event.height
        self.center_x = self.width / 2
        self.center_y = self.height / 2
        
    def draw_horizon(self, roll, pitch):
        self.delete("all")
        
        # Pitch scaling (pixels per radian)
        pitch_px = pitch * (self.height / 1.5) 
        
        # Mathematical derivation for horizon line end points
        diag = math.sqrt(self.width**2 + self.height**2) * 1.5
        
        sin_r = math.sin(-roll)
        cos_r = math.cos(-roll)
        
        # Offset due to pitch
        dy = pitch_px 
        
        x1, y1 = -diag, dy
        x2, y2 = diag, dy
        
        # Rotate points around (0,0)
        def rotate(x, y):
            rx = x * cos_r - y * sin_r
            ry = x * sin_r + y * cos_r
            return rx + self.center_x, ry + self.center_y
            
        p1 = rotate(x1, y1) # Horizon Left
        p2 = rotate(x2, y2) # Horizon Right
        p3 = rotate(x2, diag) # Bottom Right
        p4 = rotate(x1, diag) # Bottom Left
        
        # Draw Sky (Background is already cleared, but we can draw a full rect if needed)
        # Actually, draw Sky Polygon first (Top half)
        # Using canvas bg color? No, explicit sky color
        
        # Sky Points: (x1, y1) -> (x1, -diag) -> (x2, -diag) -> (x2, y2)
        s1 = rotate(x1, y1)
        s2 = rotate(x1, -diag)
        s3 = rotate(x2, -diag)
        s4 = rotate(x2, y2)
        
        self.create_polygon(s1, s2, s3, s4, fill=self.sky_color, outline="")
        self.create_polygon(p1, p2, p3, p4, fill=self.ground_color, outline="")
        
        # Horizon Line
        self.create_line(p1, p2, fill=self.line_color, width=2)
        
        # Center Crosshair (Fixed aircraft reference)
        cw = 20
        ch = 10
        self.create_line(self.center_x - cw, self.center_y, self.center_x - 5, self.center_y, fill="red", width=3) # Left Wing
        self.create_line(self.center_x + 5, self.center_y, self.center_x + cw, self.center_y, fill="red", width=3) # Right Wing
        self.create_line(self.center_x, self.center_y - 5, self.center_x, self.center_y + 5, fill="red", width=3) # Nose
        
        # DEGREE TEXT OVERLAYS 
        roll_deg = math.degrees(roll)
        pitch_deg = math.degrees(pitch)
        
        self.create_text(10, 10, text=f"R: {roll_deg:.1f}°", anchor="nw", font=("Consolas", 10, "bold"), fill="white")
        self.create_text(self.width - 10, 10, text=f"P: {pitch_deg:.1f}°", anchor="ne", font=("Consolas", 10, "bold"), fill="white")
        
        # Level Indicator
        if abs(roll_deg) < 2 and abs(pitch_deg) < 2:
            self.create_text(self.center_x, self.height - 15, text="-- LEVEL --", anchor="center", font=("Arial", 10, "bold"), fill="#2ecc71")

    def draw_hud(self, roll, pitch, arm_text, arm_color):
        self.draw_horizon(roll, pitch)
        # Overlay Arm Status
        self.create_text(self.center_x, self.center_y / 2, text=arm_text, font=("Arial", 20, "bold"), fill=arm_color)

class EKFBarWidget(tk.Canvas):
    """Mission Planner style EKF status display with VERTICAL bar graphs"""
    def __init__(self, parent, width=280, height=150, **kwargs):
        super().__init__(parent, width=width, height=height, bg="#1a1a2e", highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        
        # Initialize with zeros
        self.draw_bars({})
        
    def draw_bars(self, ekf_data):
        self.delete("all")
        
        # Parameters to display with full labels
        params = [
            ("VEL", ekf_data.get('ekf_velocity_var', 0), "Velocity"),
            ("POS", ekf_data.get('ekf_pos_horiz_var', 0), "Position"),
            ("HGT", ekf_data.get('ekf_pos_vert_var', 0), "Height"),
            ("CMP", ekf_data.get('ekf_compass_var', 0), "Compass"),
        ]
        
        # Layout
        num_bars = len(params)
        bar_width = 40
        spacing = (self.width - (num_bars * bar_width)) / (num_bars + 1)
        bar_max_height = self.height - 50  # Leave room for labels
        top_margin = 10
        
        x = spacing
        
        for label, value, full_name in params:
            # Background bar (grey track)
            bar_x1 = x
            bar_y1 = top_margin
            bar_x2 = x + bar_width
            bar_y2 = top_margin + bar_max_height
            
            self.create_rectangle(bar_x1, bar_y1, bar_x2, bar_y2, fill="#333", outline="#555")
            
            # Draw threshold zones (colored backgrounds)
            # Green zone (0-0.5)
            green_h = bar_max_height * 0.5
            self.create_rectangle(bar_x1+1, bar_y2 - green_h, bar_x2-1, bar_y2, fill="#1e4d2b", outline="")
            
            # Yellow zone (0.5-0.8)
            yellow_h = bar_max_height * 0.3
            self.create_rectangle(bar_x1+1, bar_y2 - green_h - yellow_h, bar_x2-1, bar_y2 - green_h, fill="#4d4d1e", outline="")
            
            # Red zone (0.8-1.0) 
            red_h = bar_max_height * 0.2
            self.create_rectangle(bar_x1+1, bar_y1, bar_x2-1, bar_y2 - green_h - yellow_h, fill="#4d1e1e", outline="")
            
            # Color based on value
            if value < 0.5:
                color = "#2ecc71"  # Green
            elif value < 0.8:
                color = "#f39c12"  # Amber
            else:
                color = "#e74c3c"  # Red
            
            # Fill bar from bottom up (capped at 1.0)
            fill_ratio = min(value, 1.0)
            fill_height = bar_max_height * fill_ratio
            if fill_height > 0:
                self.create_rectangle(bar_x1+2, bar_y2 - fill_height, bar_x2-2, bar_y2,
                                    fill=color, outline="")
            
            # Label at bottom
            self.create_text(x + bar_width/2, bar_y2 + 8, text=label, anchor="n",
                           font=("Arial", 8, "bold"), fill="white")
            
            # Value on top of bar
            self.create_text(x + bar_width/2, bar_y2 - fill_height - 5 if fill_height > 10 else bar_y2 - 15, 
                           text=f"{value:.2f}", anchor="s",
                           font=("Consolas", 8), fill=color)
            
            x += bar_width + spacing
        
        # Overall EKF Status at bottom
        flags = ekf_data.get('ekf_flags', 0)
        vel_var = ekf_data.get('ekf_velocity_var', 0)
        pos_var = ekf_data.get('ekf_pos_horiz_var', 0)
        vert_var = ekf_data.get('ekf_pos_vert_var', 0)
        cmp_var = ekf_data.get('ekf_compass_var', 0)
        
        # Determine EKF health based on variance values (more reliable)
        # All variances should be < 0.8 for healthy EKF
        max_var = max(vel_var, pos_var, vert_var, cmp_var)
        
        if flags == 0 and max_var == 0:
            # No data at all
            status_text = "EKF: NO DATA"
            status_color = "#7f8c8d"  # Gray
            self.ekf_ok = None
        elif max_var < 0.5:
            # All variances low = NORMAL
            status_text = "EKF NORMAL"
            status_color = "#2ecc71"  # Green
            self.ekf_ok = True
        elif max_var < 0.8:
            # Some variance elevated = CAUTION
            status_text = "EKF CAUTION"
            status_color = "#f39c12"  # Amber
            self.ekf_ok = True  # Still flyable
        else:
            # High variance = BAD
            status_text = "EKF BAD"
            status_color = "#e74c3c"  # Red
            self.ekf_ok = False
            
        self.create_text(self.width/2, self.height - 5, text=status_text, anchor="s",
                        font=("Arial", 10, "bold"), fill=status_color)

from ai_pilot import AIPilot
from backend import DroneBackend
from mission import MissionManager

class DroneApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # --- MULTI-DRONE STATE ---
        self.startup_complete = False # Flag to prevent auto-events
        self.backends = {}
        self.mission_mgrs = {}
        self.ai_pilots = {}
        self.markers_drone = {} 
        self.wp_markers = {}
        self.mission_tab_btns = {} # Store Overlay Tabs
        
        self.active_drone_idx = 1 # Will be set by add_new_drone
        self.edit_mode_index = None 
        
        # Styles
        self.setup_styles() # Move styles up so we can use them in add_new_drone if needed
        
        # UI Setup first (needed for add_new_drone to attach widgets)
        self.title("Drone Command Center 🚀 (Swarm Mode)")
        self.geometry("1400x900")
        self.minsize(800, 600)
        self.configure(bg=BG_COLOR)
        
        # Grid Config
        self.grid_columnconfigure(0, weight=0, minsize=280)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=1)

        # Fullscreen & Maximize logic...
        try:
            self.attributes('-zoomed', True)
        except:
            try: self.state('zoomed')
            except: pass
        self.bind("<F11>", self.toggle_fullscreen)
        self.fullscreen_state = False

        # Load Icon reuse logic
        self.drone_icon_img = None
        try:
            if hasattr(Image, 'Resampling'): resample = Image.Resampling.LANCZOS
            else: resample = Image.LANCZOS
            orig = Image.open("drone_icon.png")
            self.drone_icon_img = ImageTk.PhotoImage(orig.resize((50, 50), resample))
            print("Loaded drone_icon.png")
        except: pass

        self.marker_home = None
        self.marker_gcs = None 
        self.centered_map = False
        self.centered_gcs = False 
        self.trace_path = [] 
        self.gcs_loc = None 
        
        # Find GCS Location
        threading.Thread(target=self.fetch_gcs_location, daemon=True).start()

        # Create Layout Shell (Frames)
        self.create_sidebar()
        self.create_main_view()
        self.create_log_view()

        # NOW Add Initial Drone
        self.add_new_drone() # Adds Drone 0 (ID 1)
        
        self.startup_complete = True # Enable events
        self.update_loop()

    def add_new_drone(self):
        idx = len(self.backends) + 1
        print(f"Adding New Drone: ID {idx} (D{idx-1})")
        
        # Backend & Logic
        self.backends[idx] = DroneBackend(drone_id=idx)
        self.mission_mgrs[idx] = MissionManager(self.backends[idx])
        self.ai_pilots[idx] = AIPilot(self.backends[idx], self.mission_mgrs[idx], self.update_video_feed, self.add_geotag_marker)
        
        self.markers_drone[idx] = None
        self.wp_markers[idx] = []
        
        # UI: Add to Fleet List
        self.add_fleet_list_item(idx)
        
        # UI: Add Tab to Log View (if exists)
        if hasattr(self, 'log_notebook'):
             frame = ttk.Frame(self.log_notebook)
             self.log_notebook.add(frame, text=f"Drone {idx-1}")
             
             scroller = Scrollbar(frame)
             scroller.pack(side="right", fill="y")
             
             txt = tk.Text(frame, height=8, bg="black", fg="#00FF00", font=("Consolas", 10), yscrollcommand=scroller.set)
             txt.config(insertbackground="white") # Cursor color
             # Configure Tags for colored logging
             txt.tag_config("ERROR", foreground="#e74c3c")  # Red
             txt.tag_config("WARNING", foreground="#f39c12") # Orange/Amber
             txt.tag_config("SUCCESS", foreground="#2ecc71") # Green
             txt.tag_config("INFO", foreground="#3498db")    # Blue
             txt.tag_config("SYSTEM", foreground="#9b59b6")  # Purple
             
             txt.pack(side="left", fill="both", expand=True)
             scroller.config(command=txt.yview)
             
             self.log_widgets[idx] = txt
             
        # UI: Add Tab to Map Overlay (if exists)
        if hasattr(self, 'overlay_frame') and hasattr(self, 'tab_frame'):
             # We need to access the tab container. 
             # Refactoring: It's better to rebuild the tab list or append. 
             # For now, let's just recall the tab builder if possible, or append.
             # Since 'tab_frame' wasn't saved as self.tab_frame in SetupOverlay, we need to fix that.
             pass # Will handle in update_mission_tab_ui refresh or dynamic add
        
        # Select this drone if it's the first one
        if len(self.backends) == 1:
            self.select_drone(idx)
        else:
            # Maybe just select it?
            self.select_drone(idx)
            
        # Refresh Map Overlay Tabs (Hack: Re-run tab creation or append)
        # We need a robust way to update the "D0 D1 D2" tabs on the map.
        if hasattr(self, 'overlay_frame'):
            # Clear old tabs and rebuild
            for w in self.mission_tab_btns.values(): w.destroy()
            self.mission_tab_btns.clear()
            
            # We need the parent frame. 
            # In setup_overlay_window, tab_frame is local. 
            # FIX: We need to save tab_frame_ref in setup_overlay_window
            if hasattr(self, 'mission_tab_frame_ref'):
                for i in range(1, len(self.backends) + 1):
                     btn = ttk.Button(self.mission_tab_frame_ref, text=f"D{i-1}", width=5, style="HUD.TButton")
                     btn.configure(command=lambda x=i: self.switch_mission_tab(x))
                     btn.pack(side="left", padx=2, expand=True, fill="x")
                     self.mission_tab_btns[i] = btn
        
    @property
    def backend(self):
        return self.backends[self.active_drone_idx]

    @property
    def mission_mgr(self):
        return self.mission_mgrs[self.active_drone_idx]
        
    @property
    def ai_pilot(self):
        return self.ai_pilots[self.active_drone_idx]

    def shutdown(self):
        for b in self.backends.values():
            b.stop()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # General Frame Styles
        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("Sidebar.TFrame", background=SIDEBAR_COLOR)
        
        # Label Styles
        self.style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=("Consolas", 10))
        self.style.configure("Sidebar.TLabel", background=SIDEBAR_COLOR, foreground=TEXT_COLOR)
        self.style.configure("Header.TLabel", background=SIDEBAR_COLOR, foreground=TEXT_ACCENT, font=("Consolas", 18, "bold"))
        self.style.configure("Status.TLabel", background=SIDEBAR_COLOR, foreground=TEXT_COLOR, font=("Consolas", 11))
        
        # LabelFrame
        self.style.configure("TLabelframe", background=SIDEBAR_COLOR, foreground=TEXT_ACCENT, relief="solid", borderwidth=1)
        self.style.configure("TLabelframe.Label", background=SIDEBAR_COLOR, foreground=TEXT_ACCENT, font=("Consolas", 10, "bold"))
        
        # Telemetry Box Style (High Contrast)
        self.style.configure("Telemetry.TFrame", background=BG_COLOR, relief="solid", borderwidth=1)
        self.style.configure("Telemetry.TLabel", background=BG_COLOR, foreground=TEXT_ACCENT, font=("Consolas", 12, "bold"))
        self.style.configure("TelemetryVal.TLabel", background=BG_COLOR, foreground="white", font=("Consolas", 14, "bold"))
        
        # Buttons (Bold & Blocky)
        self.style.configure("TButton", font=("Consolas", 11, "bold"), padding=5, borderwidth=1, relief="raised")
        self.style.map("TButton", background=[('active', '#333333')], foreground=[('active', 'white')])
        
        # Connect/Disconnect Button Style (Neon)
        self.style.configure("Connect.TButton", font=("Consolas", 10, "bold"), background=BTN_SUCCESS, foreground="black", padding=(10, 5))
        self.style.map("Connect.TButton", 
                       background=[('active', '#CCFFCC'), ('pressed', '#004400')],
                       foreground=[('active', 'black')])
        
        # Flight Control Styles (Tactical)
        # Action (Blue)
        self.style.configure("Action.TButton", font=("Consolas", 10, "bold"), background=BTN_ACTION, foreground="black")
        self.style.map("Action.TButton", background=[('active', '#66CCFF'), ('pressed', '#005588')]) 
        
        # Warning (Orange)
        self.style.configure("Warn.TButton", font=("Consolas", 10, "bold"), background=BTN_WARN, foreground="black")
        self.style.map("Warn.TButton", background=[('active', '#FFAA66'), ('pressed', '#CC4400')])
        
        # Danger (Red)
        self.style.configure("Danger.TButton", font=("Consolas", 10, "bold"), background=BTN_DANGER, foreground="white")
        self.style.map("Danger.TButton", background=[('active', '#FF6666'), ('pressed', '#8B0000')])
        
        # EMERGENCY (Big & Bold)
        self.style.configure("Emergency.TButton", font=("Consolas", 14, "bold"), background="#FF0000", foreground="white", padding=10, borderwidth=3)
        self.style.map("Emergency.TButton", background=[('active', '#FFffff'), ('pressed', '#8b0000')])
        
        self.style.map("Success.TButton", background=[('disabled', '#333333')])
        self.style.map("Warn.TButton", background=[('disabled', '#333333')])
        self.style.map("Action.TButton", background=[('disabled', '#333333')])

        # HUD Styles
        self.style.configure("HUD.TButton", background="#333333", foreground="white", font=("Consolas", 10, "bold"), borderwidth=1)
        self.style.map("HUD.TButton",
            background=[('active', TEXT_ACCENT), ('disabled', '#111111')],
            foreground=[('active', 'black'), ('disabled', '#555555')]
        )
        self.style.configure("HUDWarn.TButton", background=BTN_DANGER, foreground="white", font=("Consolas", 10, "bold"))
        self.style.map("HUDWarn.TButton", background=[('active', '#FF5555')])

    def create_sidebar(self):
        # 1. SETUP LAYOUT - Master-Detail
        # Row 0: Fleet List (Master) - Weight 1 (Expandable)
        # Row 1: Detail Panel (Detail) - Weight 0 (Fixed/Fit)
        
        self.grid_columnconfigure(0, weight=0, minsize=310)
        self.grid_columnconfigure(1, weight=1)
        
        # Container for Column 0 (Strict Width)
        sidebar_container = tk.Frame(self, bg=SIDEBAR_COLOR, width=400)
        sidebar_container.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sidebar_container.grid_propagate(False) # Prevents children from expanding sidebar
        
        sidebar_container.grid_rowconfigure(0, weight=1) # Fleet List expands
        sidebar_container.grid_rowconfigure(1, weight=0) # Detail Panel fixed
        
        # A. FLEET LIST FRAME (Top)
        self.frame_fleet = ttk.LabelFrame(sidebar_container, text="FLEET OVERVIEW", style="TLabelframe")
        self.frame_fleet.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # Scrollable Canvas for Fleet List
        self.canvas_fleet = tk.Canvas(self.frame_fleet, bg=SIDEBAR_COLOR, highlightthickness=0)
        self.scroll_fleet = ttk.Scrollbar(self.frame_fleet, orient="vertical", command=self.canvas_fleet.yview)
        self.canvas_fleet.configure(yscrollcommand=self.scroll_fleet.set)
        
        self.scroll_fleet.pack(side="right", fill="y")
        self.canvas_fleet.pack(side="left", fill="both", expand=True)
        
        self.inner_fleet = ttk.Frame(self.canvas_fleet, style="Sidebar.TFrame")
        self.win_fleet = self.canvas_fleet.create_window((0, 0), window=self.inner_fleet, anchor="nw")
        
        self.inner_fleet.bind("<Configure>", lambda e: self.canvas_fleet.configure(scrollregion=self.canvas_fleet.bbox("all")))
        self.canvas_fleet.bind("<Configure>", lambda e: self.canvas_fleet.itemconfig(self.win_fleet, width=e.width))
        
        # B. DETAIL PANEL FRAME (Bottom)
        self.frame_detail = ttk.LabelFrame(sidebar_container, text="DRONE CONTROL", style="TLabelframe")
        self.frame_detail.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        
        # Populate
        self.create_fleet_list()
        self.create_detail_panel()

    def create_fleet_list(self): # Renaming conceptually to setup but keeping name if called elsewhere (it is called in create_sidebar)
        # 1. Initialize Container
        self.fleet_widgets = {} 
        
        # 2. Add Button Frame (At Bottom of inner_fleet)
        # We need a frame that holds the list items, and then the button below it?
        # Actually inner_fleet IS the list container.
        
        # We want functionality: add to list.
        # Let's just create the "Add" button here, but pack it LAST.
        # But if we add items dynamically, they pack after.
        # Solution: Two frames in inner_fleet? Or just pack_forget/pack.
        # Simpler: Frame for items, Frame for button.
        
        self.frame_fleet_items = tk.Frame(self.inner_fleet, bg=SIDEBAR_COLOR)
        self.frame_fleet_items.pack(fill="x", expand=True, anchor="n")
        
        self.frame_fleet_actions = tk.Frame(self.inner_fleet, bg=SIDEBAR_COLOR)
        self.frame_fleet_actions.pack(fill="x", pady=10)
        
        ttk.Button(self.frame_fleet_actions, text="➕ ADD DRONE", command=self.add_new_drone, style="Action.TButton").pack(fill="x", padx=10)

    def delete_drone(self, idx):
        """Delete a drone from the fleet. Shows warning if connected."""
        from tkinter import messagebox
        
        # Prevent Deleting Drone 0 (ID 1)
        if idx == 1:
            messagebox.showinfo("INFO", "Drone 0 Cannot be deleted.")
            return

        if idx not in self.backends:
            return
        
        backend = self.backends[idx]
        
        # Check if drone is linked (connected)
        if backend.connected:
            # Show warning popup
            result = messagebox.askyesno(
                "⚠️ WARNING",
                f"Drone D{idx-1} is currently CONNECTED!\n\nDo you really want to DISCONNECT and DELETE this drone?",
                icon="warning"
            )
            if not result:
                return  # User cancelled
            
            # Disconnect first
            backend.stop()
        
        # Remove from all data structures
        # 1. Stop AI Pilot if running
        if idx in self.ai_pilots:
            try:
                self.ai_pilots[idx].stop()
            except: pass
            del self.ai_pilots[idx]
        
        # 2. Remove mission manager
        if idx in self.mission_mgrs:
            del self.mission_mgrs[idx]
        
        # 3. Remove backend
        del self.backends[idx]
        
        # 4. Remove map marker
        if idx in self.markers_drone and self.markers_drone[idx]:
            try:
                self.markers_drone[idx].delete()
            except: pass
            del self.markers_drone[idx]
        
        # 5. Remove waypoint markers
        if idx in self.wp_markers:
            for m in self.wp_markers[idx]:
                try: m.delete()
                except: pass
            del self.wp_markers[idx]
        
        # 6. Remove fleet widget (UI)
        if idx in self.fleet_widgets:
            self.fleet_widgets[idx]['frame'].destroy()
            del self.fleet_widgets[idx]
        
        # 7. Remove log tab
        if idx in self.log_widgets:
            # Find and remove the tab
            try:
                for i, tab_id in enumerate(self.log_notebook.tabs()):
                    if self.log_notebook.tab(tab_id, "text") == f"Drone {idx-1}":
                        self.log_notebook.forget(tab_id)
                        break
            except: pass
            del self.log_widgets[idx]
            
        # 8. Remove Mission Tab Button (Overlay)
        if idx in self.mission_tab_btns:
            try:
                self.mission_tab_btns[idx].destroy()
            except: pass
            del self.mission_tab_btns[idx]
        
        # 9. Select another drone if the deleted one was active
        if self.active_drone_idx == idx:
            remaining = list(self.backends.keys())
            if remaining:
                self.select_drone(remaining[0])
            else:
                self.active_drone_idx = None
        
        print(f"Deleted Drone D{idx-1}")

    def add_fleet_list_item(self, i):
        # Creates summary widget for drone i
        
        f = tk.Frame(self.frame_fleet_items, bg=SIDEBAR_COLOR, bd=1, relief="flat")
        f.pack(fill="x", pady=2, padx=2)
        
        # Click event to select
        f.bind("<Button-1>", lambda e, idx=i: self.select_drone(idx))
        
        # Left: ID
        lbl_name = tk.Label(f, text=f"D{i-1}", font=("Consolas", 12, "bold"), bg=SIDEBAR_COLOR, fg=TEXT_COLOR, width=4)
        lbl_name.pack(side="left", padx=5)
        lbl_name.bind("<Button-1>", lambda e, idx=i: self.select_drone(idx))
        
        # Middle: Status Summary
        lbl_stat = tk.Label(f, text="DISARMED", font=("Consolas", 9), bg=SIDEBAR_COLOR, fg="#777777")
        lbl_stat.pack(side="left", expand=True, fill="x")
        lbl_stat.bind("<Button-1>", lambda e, idx=i: self.select_drone(idx))
        
        # Right: Bat/GPS
        lbl_info = tk.Label(f, text="--V", font=("Consolas", 9), bg=SIDEBAR_COLOR, fg="#ffff00")
        lbl_info.pack(side="right", padx=5)
        lbl_info.bind("<Button-1>", lambda e, idx=i: self.select_drone(idx))
        
        # Delete Button (X) - Only for drones > 0
        if i > 1:
            btn_del = tk.Button(f, text="X", font=("Consolas", 9, "bold"), bg=SIDEBAR_COLOR, fg="#ff0000",
                               bd=0, activebackground="#ff0000", activeforeground="black",
                               command=lambda idx=i: self.delete_drone(idx))
            btn_del.pack(side="right", padx=2)
        else:
            # Placeholder or nothing for Drone 0
            btn_del = None
            tk.Label(f, text="#", bg=SIDEBAR_COLOR, fg="#555555", font=("Consolas", 10)).pack(side="right", padx=5)
        
        self.fleet_widgets[i] = {
            'frame': f,
            'name': lbl_name,
            'status': lbl_stat,
            'info': lbl_info,
            'delete': btn_del
        }

    def create_detail_panel(self):
        # Creates ONE set of controls that targets self.active_drone_idx
        parent = self.frame_detail
        self.detail_controls = {}
        
        # 1. HEADER (Selected Drone Name)
        self.lbl_detail_header = tk.Label(parent, text="DRONE 0", font=("Consolas", 14, "bold"), bg=SIDEBAR_COLOR, fg=TEXT_COLOR)
        self.lbl_detail_header.pack(pady=5)
        
        # 2. AHRS / HORIZON
        self.ahrs_widget = AHRSWidget(parent, width=250, height=160)
        self.ahrs_widget.pack(fill="x", padx=15, pady=5)
        
        # 2b. EKF BAR DISPLAY (Vertical)
        self.ekf_widget = EKFBarWidget(parent, width=250, height=140)
        self.ekf_widget.pack(fill="x", padx=15, pady=5)
        
        # 3. CONNECTION (Moved below AHRS)
        conn_frame = ttk.Frame(parent)
        conn_frame.pack(fill="x", padx=5, pady=2)
        
        self.detail_conn_entry = ttk.Entry(conn_frame)
        self.detail_conn_entry.pack(side="left", fill="x", expand=True)
        # Default text set on select
        
        self.detail_conn_btn = ttk.Button(conn_frame, text="CONNECT", width=10, style="Connect.TButton",
                                           command=self.toggle_connection_active)
        self.detail_conn_btn.pack(side="right", padx=2)
        
        # 4. FLIGHT ACTIONS (Adjusted numbering)
        act_frame = ttk.Frame(parent)
        act_frame.pack(fill="x", padx=5, pady=5)
        
        # Row 1: Arm/Disarm
        self.detail_btn_arm = ttk.Button(act_frame, text="ARM", style="Warn.TButton", width=8,
                                         command=lambda: self.backends[self.active_drone_idx].arm_disarm(True, force=False))
        self.detail_btn_arm.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        
        self.detail_btn_disarm = ttk.Button(act_frame, text="DISARM", style="Danger.TButton", width=8,
                                            command=lambda: self.backends[self.active_drone_idx].arm_disarm(False, force=True))
        self.detail_btn_disarm.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        
        act_frame.grid_columnconfigure(0, weight=1)
        act_frame.grid_columnconfigure(1, weight=1)
        
        # Row 2: Takeoff/Land
        self.detail_btn_takeoff = ttk.Button(act_frame, text="TAKEOFF", style="Action.TButton",
                                             command=self.do_takeoff_active)
        self.detail_btn_takeoff.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        
        self.detail_btn_land = ttk.Button(act_frame, text="LAND", style="Action.TButton",
                                          command=lambda: self.backends[self.active_drone_idx].set_mode("LAND"))
        self.detail_btn_land.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        
        # Row 3: RTL / Mode
        self.detail_btn_rtl = ttk.Button(act_frame, text="RTL", style="Action.TButton",
                                          command=lambda: self.backends[self.active_drone_idx].set_mode("RTL"))
        self.detail_btn_rtl.grid(row=2, column=0, padx=2, pady=2, sticky="ew")
        
        # Mode Combo
        self.detail_mode_combo = ttk.Combobox(act_frame, values=["STABILIZE", "LOITER", "GUIDED", "RTL", "LAND", "AUTO"], state="readonly", width=8)
        self.detail_mode_combo.set("LOITER")
        self.detail_mode_combo.grid(row=2, column=1, padx=2, pady=2, sticky="ew")
        self.detail_mode_combo.bind("<<ComboboxSelected>>", lambda e: self.backends[self.active_drone_idx].set_mode(self.detail_mode_combo.get()))

        # 3b. ALTITUDE & SPEED CONTROLS (Two rows to save width)
        ctrl_frame = ttk.Frame(parent, padding=2)
        ctrl_frame.pack(fill="x", padx=10, pady=5)
        
        # Row 0: Altitude Control
        alt_f = ttk.Frame(ctrl_frame)
        alt_f.pack(fill="x", pady=2)
        tk.Label(alt_f, text="ALT(m):", bg=SIDEBAR_COLOR, fg=TEXT_COLOR, font=("Consolas", 10), width=8, anchor="w").pack(side="left")
        self.detail_alt_entry = ttk.Entry(alt_f, width=8)
        self.detail_alt_entry.pack(side="left", padx=5)
        self.detail_alt_entry.insert(0, "10")
        ttk.Button(alt_f, text="SET", width=5, command=self.set_altitude_from_gui).pack(side="right")
        
        # Row 1: Speed Control
        spd_f = ttk.Frame(ctrl_frame)
        spd_f.pack(fill="x", pady=2)
        tk.Label(spd_f, text="SPD(m/s):", bg=SIDEBAR_COLOR, fg=TEXT_COLOR, font=("Consolas", 10), width=8, anchor="w").pack(side="left")
        self.detail_spd_entry = ttk.Entry(spd_f, width=8)
        self.detail_spd_entry.pack(side="left", padx=5)
        self.detail_spd_entry.insert(0, "5")
        ttk.Button(spd_f, text="SET", width=5, command=self.set_speed_from_gui).pack(side="right")


        # 4. TELEMETRY GRID
        tele_frame = ttk.Frame(parent, style="Telemetry.TFrame", padding=5)
        tele_frame.pack(fill="x", padx=5, pady=5)
        
        self.detail_lbl_alt = self.make_tele_label(tele_frame, "ALT", 0, 0)
        self.detail_lbl_spd = self.make_tele_label(tele_frame, "SPD", 0, 1)
        self.detail_lbl_bat = self.make_tele_label(tele_frame, "BAT", 1, 0)
        self.detail_lbl_gps = self.make_tele_label(tele_frame, "GPS", 1, 1)
        
        # EKF Monitoring Row
        self.detail_lbl_ekf_vel = self.make_tele_label(tele_frame, "EKF VEL", 2, 0)
        self.detail_lbl_ekf_pos = self.make_tele_label(tele_frame, "EKF POS", 2, 1)
        self.detail_lbl_ekf_cmps = self.make_tele_label(tele_frame, "EKF CMP", 3, 0)
        self.detail_lbl_ekf_status = self.make_tele_label(tele_frame, "EKF", 3, 1)
        
        # 5. CONSOLE / ERROR (Terminal Style)
        terminal_frame = tk.Frame(parent, bg="black", bd=1, relief="solid")
        terminal_frame.pack(fill="x", padx=10, pady=5)
        self.detail_lbl_status = tk.Label(terminal_frame, text="Status: READY", bg="black", fg="#00FF00", font=("Consolas", 9, "bold"), anchor="w", padx=5, pady=2, wraplength=250)
        self.detail_lbl_status.pack(fill="x")
        
        # 6. SMART EMERGENCY
        ttk.Button(parent, text="🚨 SMART STOP", style="Emergency.TButton",
                   command=lambda: self.smart_stop_panel(self.active_drone_idx)).pack(fill="x", padx=5, pady=10)

    def select_drone(self, idx):
        if idx not in self.backends: return
        self.active_drone_idx = idx
        
        # Visual Update on Fleet List
        for i, w in self.fleet_widgets.items():
            if i == idx:
                w['frame'].config(bg="#006400") # Dark Green highlight
                w['name'].config(bg="#006400", fg="#00ff00")
                w['status'].config(bg="#006400", fg="white")
                w['info'].config(bg="#006400")
            else:
                w['frame'].config(bg=SIDEBAR_COLOR) # Reset
                w['name'].config(bg=SIDEBAR_COLOR, fg=TEXT_COLOR)
                w['status'].config(bg=SIDEBAR_COLOR, fg="#888888")
                w['info'].config(bg=SIDEBAR_COLOR)
                
        # Update Detail Header
        color = TEXT_COLOR
        self.lbl_detail_header.config(text=f"DRONE {idx-1} (D{idx-1})", fg=color)
        
        # Update Connection Entry Text
        # Assuming we store connection strings in backend or separate dict?
        # For now, default based on ID
        default_port = f"/dev/ttyUSB{idx-1}"
        if idx == 1: default_port = "/dev/ttyUSB0"
        elif idx == 2: default_port = "/dev/ttyACM1"
        
        # If backend has a stored connect string, use it
        if self.backends[idx].connect_str:
             self.detail_conn_entry.delete(0, "end")
             self.detail_conn_entry.insert(0, self.backends[idx].connect_str)
        else:
             self.detail_conn_entry.delete(0, "end")
             self.detail_conn_entry.insert(0, default_port)

        # Truncate loops to refresh Detail Panel immediately
        self.update_ui_stats()
        self.update_mission_header()
        self.update_map_path()
        
        # Switch Log Tab
        if idx in self.log_widgets:
             # Assuming log_widgets keys match notebook tabs order... 
             # But if dynamic addition, idx=1 -> index=0. idx=2 -> index=1.
             # This assumes sequential adding.
             try:
                self.log_notebook.select(idx-1) 
             except: pass

    def set_altitude_from_gui(self):
        """Set target altitude for the active drone"""
        try:
            alt = float(self.detail_alt_entry.get())
            if alt < 0 or alt > 500:
                print("Altitude must be between 0 and 500m")
                return
            backend = self.backends[self.active_drone_idx]
            backend.set_target_altitude(alt)
            print(f"Target altitude set to {alt}m")
        except ValueError:
            print("Invalid altitude value")
    
    def set_speed_from_gui(self):
        """Set target speed for the active drone"""
        try:
            speed = float(self.detail_spd_entry.get())
            if speed < 0 or speed > 30:
                print("Speed must be between 0 and 30 m/s")
                return
            backend = self.backends[self.active_drone_idx]
            backend.set_speed(speed)
            print(f"Speed set to {speed} m/s")
        except ValueError:
            print("Invalid speed value")

    def toggle_connection_active(self):
        if not self.startup_complete: return 
        idx = self.active_drone_idx
        backend = self.backends[idx]
        if not backend.connected:
            addr = self.detail_conn_entry.get()
            backend.connect_str = addr
            backend.start()
        else:
            backend.stop()

    def do_takeoff_active(self):
        backend = self.backends[self.active_drone_idx]
        
        # 1. Pre-Check: MUST BE ARMED
        if not backend.get_state()['armed']:
            # Log error -> TTS will speak it
            print(f"[{backend.log_prefix}] ❌ ERROR: Arm Drone First!")
            return

        # 2. Get Altitude from Entry
        try:
            alt = float(self.detail_alt_entry.get())
        except ValueError:
            alt = 10.0 # Fallback default
            
        print(f"[{backend.log_prefix}] Initiating Takeoff to {alt}m...")

        # 3. Mode Switch (GUIDED required for takeoff command)
        if backend.state['mode'] != "GUIDED":
             backend.set_mode("GUIDED")
             # Small blocking wait here is acceptable for button click
             import time
             time.sleep(0.5)
             
        # 4. Execute
        backend.takeoff(alt)

    def make_tele_label(self, parent, title, row, col):
        f = tk.Frame(parent, bg=BG_COLOR)
        f.grid(row=row, column=col, sticky="w", padx=2, pady=2)
        tk.Label(f, text=title, bg=BG_COLOR, fg="#555555", font=("Consolas", 7)).pack(anchor="w")
        lbl = tk.Label(f, text="0.0", bg=BG_COLOR, fg="white", font=("Consolas", 9, "bold"))
        lbl.pack(anchor="w")
        return lbl
        
    def update_detail_panel(self):
        # Update the ONE Detail Panel with Active Drone status
        try:
            idx = self.active_drone_idx
            
            # Safety check - ensure drone still exists
            if idx is None or idx not in self.backends:
                return
                
            backend = self.backends[idx]
            s = backend.get_state()
        except KeyError:
             # Drone might have been deleted mid-update
             return
        except Exception as e:
             # Prevent update crashes from propagating
             print(f"Update GUI Error: {e}")
             return
        
        # Connection
        if backend.connected:
            self.detail_conn_btn.config(text="DISCONNECT", state="normal", style="Connect.TButton")
            self.detail_conn_entry.config(state="disabled")
        else:
            self.detail_conn_btn.config(text="CONNECT", state="normal")
            self.detail_conn_entry.config(state="normal")
            
        # Status
        mode = s['mode']
        armed = s['armed']
        
        # Enable/Disable Buttons based on connection
        state_all = "normal" if backend.connected else "disabled"
        
        self.detail_btn_arm.config(state=state_all)
        self.detail_btn_disarm.config(state=state_all)
        self.detail_btn_takeoff.config(state=state_all)
        self.detail_btn_land.config(state=state_all)
        self.detail_btn_rtl.config(state=state_all)
        # self.detail_mode_combo.config(state="readonly" if backend.connected else "disabled") 
        # Tkinter combo disable is tricky, stick to readonly or disabled
        
        # Telemetry
        self.detail_lbl_alt.config(text=f"{s['alt_rel']:.1f} m")
        self.detail_lbl_spd.config(text=f"{s['speed']:.1f} m/s")
        self.detail_lbl_bat.config(text=f"{s['voltage']:.1f} V")
        self.detail_lbl_gps.config(text=s['gps_string'])
        
        # EKF Variance Updates (Color coded: Green < 0.5, Yellow < 1.0, Red >= 1.0)
        def ekf_color(val):
            if val < 0.5: return "#2ecc71"  # Green
            elif val < 1.0: return "#f39c12"  # Yellow
            else: return "#e74c3c"  # Red
        
        ekf_vel = s.get('ekf_velocity_var', 0)
        ekf_pos = s.get('ekf_pos_horiz_var', 0)
        ekf_cmp = s.get('ekf_compass_var', 0)
        ekf_flags = s.get('ekf_flags', 0)
        
        self.detail_lbl_ekf_vel.config(text=f"{ekf_vel:.2f}", fg=ekf_color(ekf_vel))
        self.detail_lbl_ekf_pos.config(text=f"{ekf_pos:.2f}", fg=ekf_color(ekf_pos))
        self.detail_lbl_ekf_cmps.config(text=f"{ekf_cmp:.2f}", fg=ekf_color(ekf_cmp))
        self.detail_lbl_ekf_status.config(text=f"0x{ekf_flags:02X}", fg="#2ecc71" if ekf_flags & 0x1FF == 0x1FF else "#e74c3c")
        
        # Status Text
        status_txt = f"Mode: {mode} | Armed: {armed}"
        if s['error']: status_txt += f" | ⚠️ {s['error']}"
        self.detail_lbl_status.config(text=status_txt, fg="#00FF00" if not s['error'] else "#e74c3c")
        
        # Update AHRS / Artificial Horizon
        # Roll/Pitch in radians assumed by AHRSWidget
        if hasattr(self, 'ahrs_widget'):
            roll = s['roll']
            pitch = s['pitch']
            arm_txt = "ARMED" if armed else "DISARMED"
            arm_col = "red" if armed else "#2ecc71" # Red for danger/armed, green for safe
            self.ahrs_widget.draw_hud(roll, pitch, arm_txt, arm_col)
        
        # Update EKF Bar Graph (Mission Planner Style)
        if hasattr(self, 'ekf_widget'):
            self.ekf_widget.draw_bars(s)
            
            # EKF Status Logging
            ekf_ok = getattr(self.ekf_widget, 'ekf_ok', None)
            last_ekf_ok = getattr(self, '_last_ekf_ok', None)
            
            if ekf_ok is True and last_ekf_ok is not True:
                # Just became normal - print once
                print(f"[D{idx-1}] EKF Status: NORMAL")
            elif ekf_ok is False:
                # EKF is bad - print repeatedly (every update)
                print(f"[D{idx-1}] ⚠️ EKF Status: BAD")
            
            self._last_ekf_ok = ekf_ok
            
            # EKF FAILSAFE: Auto-LAND if EKF is bad and drone is ARMED
            if ekf_ok is False:
                if armed and mode != "LAND":
                    print(f"⚠️ EKF FAILSAFE: Switching to LAND mode!")
                    backend.set_mode("LAND")
                    self.flash_emergency(True, msg="EKF FAILSAFE: LANDING!")
        
        # OSD Updates
        self.update_osd_stats(s)
        
        # Flash Emergency logic (Global)
        if s['error'] and "PreArm" not in s['error']:
             self.flash_emergency(True, msg=f"D{idx-1}: {s['error']}")
        else:
             self.flash_emergency(False)
             
        # UPDATE MAP STATUS OVERLAY
        if hasattr(self, 'lbl_map_status'):
             # Use status_text from ArduPilot or error or just Mode
             msg = s.get('status_text', '')
             if not msg: msg = f"Mode: {mode}"
             
             # Color Logic
             fg_col = "white"
             if "Ready" in msg or "ARMED" in msg: fg_col = "#00ff00" # Green
             elif "Error" in msg or "Fail" in msg or "PreArm" in msg: fg_col = "#ff0000" # Red
             else: fg_col = "#00d2d3" # Blue/Info
             
             # If Ready to Arm is true but msg is old, force it?
             if s.get('ready_to_arm') and "Ready" not in msg:
                 msg = "✅ READY TO ARM"
                 fg_col = "#00ff00"
                 
             self.lbl_map_status.config(text=msg, fg=fg_col)

    def set_active_mission_drone(self, idx):
        self.active_drone_idx = idx
        # Visual feedback on map is enough (marker highlight?)
        # User requested to remove the buttons, so no button update here.
            
        # Refresh Mission Header

        self.update_mission_header()
        self.update_map_path()
        


    # Replaces existing toggle_connection and check_single_connection


    def create_emergency_overlay(self):
        # Full screen red fade
        self.emerg_overlay = tk.Toplevel(self)
        self.emerg_overlay.attributes('-fullscreen', True)
        self.emerg_overlay.attributes('-alpha', 0.0) # Start invisible
        self.emerg_overlay.attributes('-topmost', True)
        self.emerg_overlay.config(bg="red")
        self.emerg_overlay.overrideredirect(True)
        self.emerg_overlay.withdraw() # Hide initially
        
        # Centered Warning Text
        self.lbl_emerg = tk.Label(self.emerg_overlay, text="⚠️ CRITICAL ALERT ⚠️\nCHECK SYSTEM", font=("Arial", 40, "bold"), fg="white", bg="red")
        self.lbl_emerg.place(relx=0.5, rely=0.5, anchor="center")

    def flash_emergency(self, is_active, msg=""):
        if is_active:
            self.emerg_overlay.deiconify()
            self.lbl_emerg.config(text=f"⚠️ CRITICAL ALERT ⚠️\n{msg}")
            # Simple pulse effect
            alpha = (math.sin(time.time() * 10) + 1) / 4 + 0.1 # Oscillate 0.1 to 0.6
            self.emerg_overlay.attributes('-alpha', alpha)
        else:
            self.emerg_overlay.withdraw()

    def create_main_view(self):
        # Map Frame
        map_container = ttk.Frame(self, style="TFrame")
        map_container.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        self.map_view = tkintermapview.TkinterMapView(map_container, corner_radius=10)
        self.map_view.pack(fill="both", expand=True)
        
        # Satellite View (Hybrid: Satellite + Labels)
        self.map_view.set_tile_server("https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        self.map_view.set_position(35.363, 138.730) # Fuji
        self.map_view.set_zoom(15)
        
        # Events
        # Events
        self.map_view.add_right_click_menu_command(label="Add Waypoint 📍", command=self.add_wp, pass_coords=True)
        self.map_view.add_right_click_menu_command(label="Set Home 🏠", command=self.set_custom_home, pass_coords=True)
        self.map_view.add_left_click_map_command(self.add_wp)

        # Overlay Controls (Mission) - EMBEDDED HUD
        self.setup_overlay_window()
        self.create_emergency_overlay()

    def create_log_view(self):
        log_container = ttk.Frame(self, style="TFrame")
        log_container.grid(row=1, column=1, sticky="nsew", padx=10, pady=10) # sticky="nsew" fills gap
        
        # SPLIT LOG CONTAINER: LEFT = LOGS, RIGHT = CAMERA
        log_container.grid_columnconfigure(0, weight=1) # Log takes rest
        log_container.grid_columnconfigure(1, weight=0) # Camera fixed width
        
        # --- LEFT: NOTEBOOK LOG PANELS ---
        dual_log_frame = ttk.Frame(log_container, style="TFrame")
        dual_log_frame.grid(row=0, column=0, sticky="nsew", padx=(0,5))
        
        self.log_notebook = ttk.Notebook(dual_log_frame)
        self.log_notebook.pack(fill="both", expand=True)
        
        # Create Log Widgets Dict (Empty - populated by add_new_drone)
        self.log_widgets = {} 
        
        # --- RIGHT: VIDEO FEED ---
        video_outer = ttk.Frame(log_container, style="Telemetry.TFrame", padding=2)
        video_outer.grid(row=0, column=1, sticky="nsew")
        
        # Video Header
        tk.Label(video_outer, text="LIVE SENSOR FEED", bg="#222f3e", fg="red", font=("Consolas", 8)).pack(fill="x")
        
        # Video Feed
        self.lbl_video = ttk.Label(video_outer, text="[NO SIGNAL]", anchor="center", background="black", foreground="white")
        self.lbl_video.pack(side="top", padx=2, pady=2)
        
        # AI Control Switch (Below Video) and overlaying it? 
        self.var_ai_enable = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(video_outer, text="ENABLE AI TRACKING", variable=self.var_ai_enable, 
                             bg="#222f3e", fg="white", selectcolor="#222f3e", activebackground="#222f3e", activeforeground="white",
                             command=self.toggle_ai, font=("Arial", 9, "bold"))
        chk.pack(side="bottom", fill="x")

        # Redirect Prints... (Rest of function)
        import sys
        import datetime
        import queue
        
        self.log_queue = queue.Queue()
        self.tts_queue = queue.Queue()
        
        # Start TTS Worker
        threading.Thread(target=self.process_tts_queue, daemon=True).start()
        
        # Separate log logic handles via poll loop
        
        class Redirect:
            def __init__(self, queue):
                self.queue = queue
                self.buffer = ""
            def write(self, string):
                self.buffer += string
                while "\n" in self.buffer:
                    line, self.buffer = self.buffer.split("\n", 1)
                    if line: self.queue.put(line)
            def flush(self):
                pass  
        sys.stdout = Redirect(self.log_queue)
        
        self.poll_log_queue()
        print("Welcome to Drone Command Center 🚀 initialized.")

    def process_tts_queue(self):
        """Worker thread for serial text-to-speech"""
        import subprocess
        import time
        while True:
            try:
                msg = self.tts_queue.get()
                # Run spd-say with --wait to ensure serial speaking
                # Using subprocess.run ensures we block this thread until speech is done (or handed off)
                # spd-say --wait requires the speech-dispatcher to signal completion
                subprocess.run(["spd-say", "--wait", msg])
                time.sleep(1.5) # Add delay between messages
                self.tts_queue.task_done()
            except Exception as e:
                print(f"TTS Error: {e}")
                pass
                print(f"TTS Error: {e}")
                pass

    def poll_log_queue(self):
        try:
            while True:
                s = self.log_queue.get_nowait()
                # Categorize Log
                category = 'sys'
                # Improved Parsing for N drones
                if "[D" in s:
                    # quick parse "[D0]" -> 1
                    try:
                        start = s.find("[D") + 2
                        end = s.find("]", start)
                        d_id = int(s[start:end]) + 1 # Convert 0-index to 1-index ID
                        category = d_id
                    except:
                        pass
                
                # --- TTS INTEGRATION ---
                # Speak critical errors
                if "ERROR" in s or "FAIL" in s or "WARNING" in s or "PreArm" in s:
                    # Sanitize message for shell
                    clean_msg = s.replace("'", "").replace('"', "").replace("(", "").replace(")", "")
                    clean_msg = clean_msg.replace("D0", "Drone Zero").replace("D1", "Drone One")
                    # Limit length to avoid long monologues
                    if len(clean_msg) > 100: clean_msg = clean_msg[:100]
                    
                    # Push to Queue for Serial Speaking
                    self.tts_queue.put(clean_msg)
                # -----------------------
                
                timestamp = datetime.datetime.now().strftime("[%H:%M:%S] ")
                formatted_line = timestamp + s + "\n"
            
                # DIRECT LOGGING TO SPLIT PANELS
                # Drone 0 (ID 1) -> Left Panel (log_text0)
                # Drone 1 (ID 2) -> Right Panel (log_text1)
                # System/Other -> BOTH? Or Left default? Let's put Sys in BOTH for visibility or just Left.
                # User asked for "Invidiual Drone", implies specific.
                
                if isinstance(category, int):
                     if category in self.log_widgets:
                         self._append_log(self.log_widgets[category], formatted_line)
                else:
                     # System logs go to ALL tabs? Or just currently selected?
                     # Let's put in all for safety, or just first one.
                     for w in self.log_widgets.values():
                         self._append_log(w, formatted_line)

        except queue.Empty:
            pass
        self.after(100, self.poll_log_queue)
        
    def _append_log(self, widget, text):
        widget.config(state='normal')
        
        # Determine tag based on content
        tag = None
        upper_text = text.upper()
        
        if any(x in upper_text for x in ["❌", "ERROR", "FAIL", "FAILED", "BAD"]):
            tag = "ERROR"
        elif any(x in upper_text for x in ["⚠️", "WARNING", "WRN", "PREARM"]):
            tag = "WARNING"
        elif any(x in upper_text for x in ["✅", "SUCCESS", "OK", "NORMAL", "ARMED", "READY"]):
            tag = "SUCCESS"
        elif any(x in upper_text for x in ["🔄", "MODE", "SET", "COMMAND"]):
            tag = "SYSTEM"
        elif any(x in upper_text for x in ["🛰️", "GPS", "BAT", "HDOP"]):
            tag = "INFO"

        widget.insert("end", text, tag)
        widget.see("end")
        widget.config(state='disabled')

    def refresh_console(self):
        pass # No longer needed with split view
            


    def create_osd_stats(self):
        # On-Screen Display (OSD) Stats - EMBEDDED DIRECTLY ON MAP
        # Note: Tkinter labels have a background color. We use the dark theme color.
        
        # Bottom Left Container (Bat, GPS, HDOP)
        self.osd_frame_bl = tk.Frame(self.map_view, bg=SIDEBAR_COLOR)
        self.osd_frame_bl.place(relx=0.02, rely=0.98, anchor="sw")
        
        # REMOVED EMOJI due to hang
        self.osd_bat = tk.Label(self.osd_frame_bl, text="BAT -- V", font=("Segoe UI", 16, "bold"), fg=BTN_WARN, bg=SIDEBAR_COLOR)
        self.osd_bat.pack(side="left", padx=5)
        
        self.osd_gps = tk.Label(self.osd_frame_bl, text="NO GPS", font=("Segoe UI", 16, "bold"), fg=BTN_DANGER, bg=SIDEBAR_COLOR)
        self.osd_gps.pack(side="left", padx=5)
        
        self.osd_hdop = tk.Label(self.osd_frame_bl, text="HDOP: --", font=("Segoe UI", 16, "bold"), fg=BTN_WARN, bg=SIDEBAR_COLOR)
        self.osd_hdop.pack(side="left", padx=5)
        
        # Bottom Right Container (Alt, Dist)
        self.osd_frame_br = tk.Frame(self.map_view, bg=SIDEBAR_COLOR)
        self.osd_frame_br.place(relx=0.98, rely=0.98, anchor="se")
        
        self.osd_alt = tk.Label(self.osd_frame_br, text="ALT: -- m", font=("Segoe UI", 16, "bold"), fg="white", bg=SIDEBAR_COLOR)
        self.osd_alt.pack(side="top", anchor="e")
        
        self.osd_dist = tk.Label(self.osd_frame_br, text="DIS: -- m", font=("Segoe UI", 16, "bold"), fg=TEXT_ACCENT, bg=SIDEBAR_COLOR)
        self.osd_dist.pack(side="top", anchor="e")
        
        # Top Center Container (Arm Status)
        self.osd_frame_top = tk.Frame(self.map_view, bg=SIDEBAR_COLOR)
        self.osd_frame_top.place(relx=0.5, rely=0.05, anchor="n")

        self.osd_arm = tk.Label(self.osd_frame_top, text="DISARMED", font=("Segoe UI", 20, "bold"), fg=BTN_DANGER, bg=SIDEBAR_COLOR)
        self.osd_arm.pack()

        # Bottom Center Container (Status Text)
        self.osd_frame_bc = tk.Frame(self.map_view, bg=SIDEBAR_COLOR)
        self.osd_frame_bc.place(relx=0.5, rely=0.90, anchor="s")

        self.osd_status = tk.Label(self.osd_frame_bc, text="", font=("Segoe UI", 14, "bold"), fg=BTN_DANGER, bg=SIDEBAR_COLOR)
        self.osd_status.pack()

    def setup_overlay_window(self):
        self.create_osd_stats()
        
        # EMBEDDED FRAME (Mission Control)
        # We place it directly on top of the map_view widget
        
        # Container for the HUD
        self.overlay_frame = tk.Frame(self.map_view, bg=SIDEBAR_COLOR, highlightthickness=0)
        self.overlay_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)
        
        # Header
        self.lbl_mission_header = tk.Label(self.overlay_frame, text="DRONE 0 MISSION", font=("Segoe UI", 10, "bold"), bg=SIDEBAR_COLOR, fg=TEXT_ACCENT)
        self.lbl_mission_header.pack(pady=2, fill="x", padx=5)
        
        # STATUS OVERLAY (User Request)
        self.lbl_map_status = tk.Label(self.overlay_frame, text="-- NOT CONNECTED --", font=("Segoe UI", 9, "bold"), bg=SIDEBAR_COLOR, fg=BTN_WARN, wraplength=200)
        self.lbl_map_status.pack(pady=2, fill="x")

        # DRONE SELECTOR TABS (Dynamic Button Bar)
        tab_frame = tk.Frame(self.overlay_frame, bg=SIDEBAR_COLOR)
        tab_frame.pack(fill="x", pady=2, padx=5)
        self.mission_tab_frame_ref = tab_frame # Save ref for dynamic updates
        
        self.mission_tab_btns = {} 
        
        # Initial Population (Usually just 1 if called from __init__ -> add_new_drone order?)
        # Actually setup_overlay_window is called in create_main_view, which is called BEFORE add_new_drone.
        # So initially backends is empty.
        # We rely on add_new_drone to populate this.
        # But we loop self.backends here?
        
        for i in range(1, len(self.backends) + 1):
             btn = ttk.Button(tab_frame, text=f"D{i-1}", width=5, style="HUD.TButton")
             btn.configure(command=lambda idx=i: self.switch_mission_tab(idx)) 
             
             btn.pack(side="left", padx=2, expand=True, fill="x")
             self.mission_tab_btns[i] = btn
             
        # Waypoint List
        self.wp_list = Listbox(self.overlay_frame, height=6, width=25, bg="#333333", fg="white", bd=0, highlightthickness=0, font=("Consolas", 9))
        self.wp_list.pack(pady=2, padx=5)
        
        # Buttons
        btn_frame = tk.Frame(self.overlay_frame, bg=SIDEBAR_COLOR)
        btn_frame.pack(fill="x", pady=2, padx=5)
        
        ttk.Button(btn_frame, text="Delete ✕", width=8, command=self.delete_selected_wp, style="HUDWarn.TButton").pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Edit ✎", width=8, command=self.start_edit_wp, style="HUD.TButton").pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Clear 🗑", width=8, command=self.clear_mission_verify, style="HUDWarn.TButton").pack(side="right", padx=2)
        
        # Initial Mission Upload Button
        self.btn_upload = ttk.Button(self.overlay_frame, text="Upload Mission 📤", command=self.upload_mission, style="HUD.TButton")
        self.btn_upload.pack(pady=5, padx=5, fill="x")
        
        self.btn_start = ttk.Button(self.overlay_frame, text="START GUIDED ▶", command=self.start_mission, state="disabled", style="HUDSuccess.TButton")
        self.btn_start.pack(pady=5, padx=5, fill="x")
        
        # BREAK / CONTINUE CONTROLS
        ctrl_frame = tk.Frame(self.overlay_frame, bg=SIDEBAR_COLOR)
        ctrl_frame.pack(fill="x", pady=5, padx=5)
        
        self.btn_pause = ttk.Button(ctrl_frame, text="BREAK ⏸", width=8, command=self.pause_mission_panel, style="HUDWarn.TButton")
        self.btn_pause.pack(side="left", padx=2, expand=True, fill="x")
        
        self.btn_drop = ttk.Button(ctrl_frame, text="DROP 📦", width=8, command=self.drop_payload_panel, style="HUD.TButton")
        self.btn_drop.pack(side="left", padx=2, expand=True, fill="x")
        
        self.btn_resume = ttk.Button(ctrl_frame, text="CONTINUE ▶", width=8, command=self.resume_mission_panel, style="HUD.TButton")
        self.btn_resume.pack(side="left", padx=2, expand=True, fill="x")

        # MAP CLICK TOGGLE (Added per user request)
        # Default False (Unchecked) for safety
        self.var_map_click = tk.BooleanVar(value=False)
        self.chk_map = tk.Checkbutton(self.overlay_frame, text="Enable Map Clicks", variable=self.var_map_click, 
                                      bg=SIDEBAR_COLOR, fg=TEXT_COLOR, selectcolor=SIDEBAR_COLOR, activebackground=SIDEBAR_COLOR, activeforeground=TEXT_COLOR)
        self.chk_map.pack(pady=2, padx=5, fill="x")


    def on_root_map(self, event):
        pass

    def on_root_unmap(self, event):
        pass
    
    def sync_mission_widget_pos(self, event=None):
        pass
            
    # --- ACTIONS ---
    
    def toggle_connection(self, drone_idx):
        backend = self.backends[drone_idx]
        if not backend.connected:
            # START CONNECTING
            if drone_idx == 1:
                addr = self.entry_conn1.get()
                btn = self.btn_connect1
                entry = self.entry_conn1
            else:
                addr = self.entry_conn2.get()
                btn = self.btn_connect2
                entry = self.entry_conn2
                
            backend.connect_str = addr
            backend.start()
            self.centered_map = False # Reset for new connection (maybe per drone?)
            
            # UI Feedback
            btn.config(text="...", state="disabled")
            entry.config(state="disabled")
            
            # Start Polling
            # We can spawn a thread or use after() per drone.
            # Simple approach: Check in generic loop or specific check
            self.check_single_connection(drone_idx, time.time())
        else:
            # DISCONNECT
            backend.stop()
            if drone_idx == 1:
                self.btn_connect1.config(text="LINK", state="normal", style="Connect.TButton")
                self.entry_conn1.config(state="normal")
            else:
                self.btn_connect2.config(text="LINK", state="normal", style="Connect.TButton")
                self.entry_conn2.config(state="normal")
                
    def smart_stop_panel(self, drone_idx):
        # Trigger Smart Emergency for SPECIFIC drone
        print(f"TRIGGERING SMART EMERGENCY FOR DRONE {drone_idx-1}")
        self.backends[drone_idx].smart_emergency_land()

    def check_single_connection(self, drone_idx, start_time):
        backend = self.backends[drone_idx]
        if drone_idx == 1:
            btn = self.btn_connect1
        else:
            btn = self.btn_connect2
            
        if backend.connected:
             btn.config(text="UNLINK", state="normal")
             # Success
        elif time.time() - start_time > 10:
             # Timeout
             backend.stop()
             btn.config(text="LINK", state="normal")
             if drone_idx == 1: self.entry_conn1.config(state="normal")
             else: self.entry_conn2.config(state="normal")
             messagebox.showerror("Error", f"Drone {drone_idx} Connection Timeout")
        else:
             self.after(500, lambda: self.check_single_connection(drone_idx, start_time))


    def on_drone_switch(self):
        # self.active_drone_idx = self.var_drone_sel.get() # REMOVING: Causing stale state revert
        # We now manage active_drone_idx manually in switch_mission_tab
        print(f"[GUI] Switched to Drone {self.active_drone_idx}")

        
        # Refresh UI immediately - PASS THE ACTIVE STATE
        # Note: self.backend property automatically uses active_drone_idx
        # FIXED: update_ui_stats takes no arguments now, it fetches state internally.
        self.update_ui_stats()

        
        # Refresh Mission View
        self.update_mission_header()
        self.update_map_path()
        # Refresh Console
        self.refresh_console()

        
    # --- TAB SWITCHING LOGIC ---
    def switch_mission_tab(self, drone_idx):
        # Direct Switch - Bypass Variable Triggers to avoid circular logic or missing vars
        self.active_drone_idx = drone_idx
        # self.var_drone_sel.set(drone_idx) # Redundant if we manually update
        
        self.on_drone_switch()

    def update_mission_header(self):
        # Update styling of tabs to show active
        d_idx = self.active_drone_idx
        
        self.lbl_mission_header.config(text=f"DRONE {d_idx-1} MISSION", fg="#00d2d3" if d_idx==1 else "#e056fd")
        
        # Highlight Tabs
        for idx, btn in self.mission_tab_btns.items():
            if idx == d_idx:
                btn.state(["pressed"])
            else:
                btn.state(["!pressed"])
        
        # ENABLE CONTROLS only if this drone is active (always true for this logic)
        state_flag = "!disabled"
        if hasattr(self, 'btn_pause'): self.btn_pause.state([state_flag])
        if hasattr(self, 'btn_drop'): self.btn_drop.state([state_flag])
        if hasattr(self, 'btn_resume'): self.btn_resume.state([state_flag])




    def smart_stop(self):
        # Ascend 4m -> Hover 3s -> Land
        self.backend.smart_emergency_land()
            
    def add_wp(self, coords):
        # GUARD: Check if Map Clicking is Enabled
        if not self.var_map_click.get():
             # print("Map click ignored (Checkbox disabled)")
             return

        
    # 0. Check if selecting a drone first (REMOVED per user request)
    # The user wants both displayed simultaneously without map-click switching.
    # if self.check_drone_selection_click(coords):
    #     return

        lat, lon = coords
        
        if self.edit_mode_index is not None:
             # EDIT EXISTING
             self.mission_mgr.edit_waypoint(self.edit_mode_index, lat, lon)
             print(f"[{self.backends[self.active_drone_idx].log_prefix}] Edited WP {self.edit_mode_index} -> {lat:.5f}, {lon:.5f}")

             self.edit_mode_index = None # Exit edit mode
             self.map_view.config(cursor="") 
        else:
             # ADD NEW
             self.mission_mgr.add_waypoint(lat, lon)
             print(f"[{self.backends[self.active_drone_idx].log_prefix}] Added WP: {lat:.5f}, {lon:.5f}")
             
        self.update_map_path()

    def start_edit_wp(self):
        sel = self.wp_list.curselection()
        if sel:
            self.edit_mode_index = sel[0]
            print(f"Editing Waypoint {self.edit_mode_index}... Click map to move.")
            # Visual cue
            self.map_view.config(cursor="crosshair")
        else:
             messagebox.showinfo("Edit", "Select a waypoint to edit.")

    def set_custom_home(self, coords):
        lat, lon = coords
        self.gcs_loc = (lat, lon)
        
        # Update Marker Immediately
        if self.marker_gcs:
            self.marker_gcs.set_position(lat, lon)
        else:
             self.marker_gcs = self.map_view.set_marker(lat, lon, text="🏠 HOME", marker_color_circle="blue", marker_color_outside="cyan")
             
        # Center Map
        self.map_view.set_position(lat, lon)
        print(f"Custom Home Set: {lat}, {lon}")

    def delete_selected_wp(self):
        sel = self.wp_list.curselection()
        if sel:
            idx = sel[0]
            self.mission_mgr.remove_waypoint(idx)
            self.update_map_path()
            print(f"[{self.backends[self.active_drone_idx].log_prefix}] Deleted WP {idx}")

        else:
            messagebox.showinfo("Undo", "Select a waypoint to delete.")

    def clear_mission_verify(self):
        if messagebox.askyesno("Clear Mission", "Are you sure you want to clear all waypoints?"):
            self.clear_wps()

    def clear_wps(self):
        self.mission_mgr.clear_waypoints()
        self.update_map_path()
        print(f"[{self.backends[self.active_drone_idx].log_prefix}] Waypoints cleared.")

        
    def update_map_path(self):
        # Clear paths BUT we want to redraw them
        self.map_view.delete_all_path()
        
        # Clear Markers for ALL drones
        for idx, markers in self.wp_markers.items():
            for m in markers:
                m.delete()
            markers.clear()
            
        # Draw Missions for ALL Drones
        for idx, mgr in self.mission_mgrs.items():
             waypoints = mgr.waypoints
             coords = []
             # Drone 0 (ID 1) = Cyan, Drone 1 (ID 2) = Magenta
             color_path = "cyan" if idx == 1 else "magenta"
             color_marker = "green" if idx == 1 else "orange"
             
             prefix = f"D{idx-1}"
             
             for i, (lat, lon) in enumerate(waypoints):
                 # Add Marker
                 label = f"{prefix}:{i}" 
                 m = self.map_view.set_marker(lat, lon, text=label, marker_color_circle=color_marker)
                 self.wp_markers[idx].append(m)
                 coords.append((lat, lon))
                 
             # Draw Path Line
             if len(coords) > 1:
                 self.map_view.set_path(coords, color=color_path)

        # Update Listbox ONLY for ACTIVE drone
        self.wp_list.delete(0, 'end')
        try:
            active_waypoints = self.mission_mgrs[self.active_drone_idx].waypoints
            for i, (lat, lon) in enumerate(active_waypoints):
                 self.wp_list.insert('end', f"{i}: {lat:.5f}, {lon:.5f}")
        except KeyError:
            # Active drone might be deleted, just skip listing waypoints
            pass

        # Re-draw Trace Path (Red Line)
        if self.trace_path:
             self.map_view.set_path(self.trace_path, color="red")
        
    def do_takeoff(self):
        try:
            alt = float(self.entry_alt.get())
        except ValueError:
            alt = 5.0 # Fallback
            
        print(f"Executing Takeoff to {alt}m (Autonomous/Guided)")
        
        # 1. Enforce GUIDED Mode (Autonomous Takeoff Requirement)
        if self.backend.state['mode'] != "GUIDED":
             self.backend.set_mode("GUIDED")
             # Small blocking wait to ensure mode switch is processed by FC
             import time
             time.sleep(0.5)
        
        # 2. Send Takeoff Command
        self.backend.takeoff(altitude=alt)

             
    def start_mission(self):
        try:
            alt = float(self.entry_alt.get())
        except ValueError:
            alt = 10.0
            
        print(f"[{self.backend.log_prefix}] Starting Guided Mission with Alt: {alt}")
        
        # AUTO-ENABLE AI PILOT
        if not self.var_ai_enable.get():
            self.var_ai_enable.set(True)
            self.toggle_ai()
            print(f"[{self.backend.log_prefix}] [GUI] Auto-Enabled AI Pilot for Mission.")
            
        # EXECUTE GUIDED MISSION (Python Driven)
        self.mission_mgr.execute_guided_mission(altitude=alt)
        
    def pause_mission_panel(self):
        self.mission_mgr.pause_mission()
        
    def resume_mission_panel(self):
        self.mission_mgr.resume_mission()
        
    def drop_payload_panel(self):
        self.mission_mgr.drop_payload()


             
    def upload_mission(self):
        if self.mission_mgr.upload_mission():
            print(f"[{self.backends[self.active_drone_idx].log_prefix}] Mission Uploaded Successfully!")
        else:
            print(f"[{self.backends[self.active_drone_idx].log_prefix}] Mission Upload Failed.")


    # --- AI PILOT INTEGRATION ---
    def toggle_ai(self):
        enabled = self.var_ai_enable.get()
        self.ai_pilot.enabled = enabled
        if enabled:
            if not self.ai_pilot.running:
                self.ai_pilot.start()
            print("[GUI] Swarm AI ENABLED")
        else:
            print("[GUI] Swarm AI DISABLED")

    def update_video_feed(self, frame_rgb):
        try:
            img = Image.fromarray(frame_rgb)
            imgtk = ImageTk.PhotoImage(image=img)
            self.lbl_video.configure(image=imgtk)
            self.lbl_video.image = imgtk 
        except Exception as e:
            pass 
            
    def add_geotag_marker(self, lat, lon):
        self.after(0, lambda: self._add_geotag_marker_main(lat, lon))
        
    def _add_geotag_marker_main(self, lat, lon):
        print(f"[GUI] Marking Human at {lat}, {lon}")
        self.map_view.set_marker(lat, lon, text="HUMAN", marker_color_circle="red", marker_color_outside="yellow")

    def toggle_fullscreen(self, event=None):
        self.fullscreen_state = not self.fullscreen_state
        self.attributes("-fullscreen", self.fullscreen_state)
        return "break"

    def fetch_gcs_location(self):
        # THREAD-SAFE: Do NOT print to stdout (GUI)
        try:
            with urllib.request.urlopen("http://ip-api.com/json/", timeout=5) as url:
                data = json.loads(url.read().decode())
                if data['status'] == 'success':
                    self.gcs_loc = (data['lat'], data['lon'])
        except Exception as e:
            # Print to ORIGINAL stderr for debugging (visible in terminal)
            import sys
            print(f"GCS Thread Error: {e}", file=sys.__stderr__)

    def update_loop(self):
        has_critical_error = False
        critical_msg = ""

        # 1. UPDATE MAP & MARKERS (For ALL drones)
        for idx, backend in self.backends.items():
            # THREAD-SAFE STATE ACCESS
            s = backend.get_state()

            # Check for errors
            txt = str(s.get('statustext', '')).upper()
            if "FAILSAFE" in txt or "ERR" in txt:
                has_critical_error = True
                critical_msg = f"D{idx-1}: {txt}"
            
            # --- UPDATE FLEET LIST SUMMARY ---
            try:
                if hasattr(self, 'fleet_widgets') and idx in self.fleet_widgets:
                    w = self.fleet_widgets[idx]
                    # Status summary
                    mode_txt = s['mode']
                    if s['armed']: mode_txt = f"ARMED ({mode_txt})"
                    elif not backend.connected: mode_txt = "OFFLINE"
                    
                    w['status'].config(text=mode_txt, fg="#2ecc71" if s['armed'] else ("#e74c3c" if not backend.connected else "gray"))
                    
                    # Info
                    bat_txt = f"{s['voltage']:.1f}V"
                    if s['gps_fix'] >= 3: bat_txt += " 🛰️"
                    w['info'].config(text=bat_txt)
            except: pass
            
            if s['lat'] != 0 and s['lon'] != 0:
                try:
                    # Update/Create Marker
                    marker = self.markers_drone.get(idx)
                    if marker is None:
                        label = f"{idx-1}"
                        # Use Icon if available
                        if self.drone_icon_img:
                             marker = self.map_view.set_marker(s['lat'], s['lon'], text=label, icon=self.drone_icon_img)
                        else:
                             marker = self.map_view.set_marker(s['lat'], s['lon'], text=label, marker_color_circle="red" if idx==1 else "blue") # Default to colors
                        self.markers_drone[idx] = marker
                    else:
                        marker.set_position(s['lat'], s['lon'])
                        
                    # Auto-Center (Only on Active Drone)
                    if idx == self.active_drone_idx:
                         if not self.centered_map:
                             self.map_view.set_position(s['lat'], s['lon'])
                             self.map_view.set_zoom(18) 
                             self.centered_map = True
                except Exception as e:
                    pass
            
            # 1b. Update Home Launch Marker (If available)
            if s['home_lat'] and s['home_lon']:
                if idx == self.active_drone_idx:
                     if self.marker_home is None:
                         self.marker_home = self.map_view.set_marker(s['home_lat'], s['home_lon'], text="🚩 Launch", marker_color_circle="yellow", marker_color_outside="red")
                     else:
                         self.marker_home.set_position(s['home_lat'], s['home_lon'])

        # 2. UPDATE DETAIL PANEL (Only for ACTIVE drone)
        self.update_detail_panel()
            
        # --- GCS/Laptop Marker & Auto-Focus (RUNS ALWAYS) ---
        if self.gcs_loc:
            if self.marker_gcs is None:
                self.marker_gcs = self.map_view.set_marker(self.gcs_loc[0], self.gcs_loc[1], text="🏠 HOME", marker_color_circle="blue", marker_color_outside="cyan")
            
            if not self.centered_gcs and not self.centered_map:
                self.map_view.set_position(self.gcs_loc[0], self.gcs_loc[1])
                self.map_view.set_zoom(14)
                self.centered_gcs = True

        # Continuous visual sync
        self.sync_mission_widget_pos()

        # OSD Updates (Active Drone)
        try:
             active_s = self.backends[self.active_drone_idx].get_state()
             self.update_osd_stats(active_s)
        except Exception as e:
             pass

        # Flash Emergency if ANY drone has critical error
        if has_critical_error:
             self.flash_emergency(True, msg=critical_msg)
        else:
             self.flash_emergency(False)

        self.after(100, self.update_loop)

    def check_drone_selection_click(self, coords):
        # Determine if click is near a drone
        click_lat, click_lon = coords
        threshold = 0.0001 # ~10 meters? Very rough.
        
        for idx, backend in self.backends.items():
             s = backend.get_state()
             if s['lat'] != 0 and s['lon'] != 0:
                 dist = (s['lat'] - click_lat)**2 + (s['lon'] - click_lon)**2
                 if dist < threshold**2:
                      print(f"Map Click Selected Drone {idx}")
                      self.switch_mission_tab(idx)
                      return True
        return False


    def update_ui_stats(self):
        # LEGACY/PROXY: Redirect to update_detail_panel if called
        self.update_detail_panel()
    

    def update_osd_stats(self, s):
        # Map OSD Status
        is_armed = s['armed']
        is_ready = s['ready_to_arm']
        
        if hasattr(self, 'osd_arm') and self.osd_arm:
            if is_armed:
                self.osd_arm.config(text="ARMED", fg="#e74c3c")
            elif is_ready:
                self.osd_arm.config(text="READY TO ARM", fg="#2ecc71")
            else:
                self.osd_arm.config(text="NOT READY", fg="#f39c12")

        if hasattr(self, 'osd_status') and self.osd_status:
            if not is_ready and not is_armed:
                 # Handle possible NoneType for error
                 err_text = s.get('error') or ""
                 err_msg = err_text.replace("PreArm:", "").strip()
                 if err_msg:
                     self.osd_status.config(text=f"Check: {err_msg}")
                 else:
                     self.osd_status.config(text="Checking System...")
            else:
                 self.osd_status.config(text="")
             
        # OSD Telemetry
        if hasattr(self, 'osd_bat') and self.osd_bat:
            self.osd_bat.config(text=f"BAT {s['voltage']:.1f} V")
            
        if hasattr(self, 'osd_gps') and self.osd_gps:
            if s['gps_fix'] >= 3:
                 self.osd_gps.config(text=f"GPS LOCK ({s['gps_sats']})", fg="#2ecc71")
            else:
                 self.osd_gps.config(text="NO GPS", fg="#e74c3c")
        
        if hasattr(self, 'osd_hdop') and self.osd_hdop:
            self.osd_hdop.config(text=f"HDOP: {s['gps_hdop']:.1f}")
            
        if hasattr(self, 'osd_dist') and self.osd_dist:
            self.osd_dist.config(text=f"DIS: {s['dist_home']:.1f}m")
            
        if hasattr(self, 'osd_alt') and self.osd_alt:
            self.osd_alt.config(text=f"ALT: {s['alt_rel']:.1f}m")






