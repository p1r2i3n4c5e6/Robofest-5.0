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

# --- THEME COLORS ---
# --- THEME COLORS ---
BG_COLOR = "#2c3e50"       # Dark Blue/Slate
SIDEBAR_COLOR = "#34495e"  # Slightly lighter slate
TEXT_COLOR = "#ecf0f1"     # White-ish
BTN_SUCCESS = "#27ae60"    # Green
BTN_DANGER = "#c0392b"     # Red
BTN_ACTION = "#2980b9"     # Blue
BTN_WARN = "#e67e22"       # Orange
BTN_SUCCESS = "#27ae60"    # Green
BTN_DANGER = "#c0392b"     # Red
BTN_ACTION = "#2980b9"     # Blue
BTN_WARN = "#e67e22"       # Orange

import math

class AHRSWidget(tk.Canvas):
    def __init__(self, master, width=300, height=200):
        super().__init__(master, width=width, height=height, bg=BG_COLOR, highlightthickness=0)
        self.width = width
        self.height = height
        self.center_x = width / 2
        self.center_y = height / 2
        
        # Horizon Colors (Sky/Ground)
        self.sky_color = "#3498db"
        self.ground_color = "#2ecc71"
        self.line_color = "white"
        
        # Bind Resize
        self.bind("<Configure>", self.on_resize)
        
        # Draw Initial State
        self.draw_horizon(0, 0)
        
    def on_resize(self, event):
        self.width = event.width
        self.height = event.height
        self.center_x = self.width / 2
        self.center_y = self.height / 2
        # Redraw needed? The loop handles it, but we can force one
        # self.draw_horizon(0, 0) # Argument issue, just let loop handle
        
    def draw_horizon(self, roll, pitch):
        self.delete("all")
        
        # Pitch scaling (pixels per radian) - simple approx
        # Pitch moves the horizon line up/down
        pitch_px = pitch * (self.height / 1.5) 
        
        # Roll rotation
        # We draw a giant rectangle that is split into sky and ground, then rotate it
        # Actually easier to draw a polygon for the ground.
        
        # Mathematical derivation for horizon line end points
        # y = tan(roll) * x + offset
        
        # Simplified approach:
        # 1. Translate to center
        # 2. Rotate by roll
        # 3. Translate vertically by pitch
        
        # Using a very large polygon for Sky and Ground that extends beyond canvas
        diag = math.sqrt(self.width**2 + self.height**2) * 1.5
        
        # Create a rotated coordinate system logic or just rotate points
        sin_r = math.sin(-roll) # Negative because canvas Y is down
        cos_r = math.cos(-roll)
        
        # Offset due to pitch (moves ground up/down)
        # Positive pitch = nose up = ground goes down
        dy = pitch_px 
        
        # Points for the dividing line (Horizon) in unrotated coordinates
        # Center is (0, dy) relative to canvas center
        # Line extends -diag to +diag in X
        
        x1, y1 = -diag, dy
        x2, y2 = diag, dy
        
        # Points for Ground Polygon (Below horizon)
        # (x2, y2) -> (x2, diag) -> (x1, diag) -> (x1, y1)
        
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
        
        # DEGREE TEXT OVERLAYS (Mission Planner Style)
        # Roll (Top Left)
        roll_deg = math.degrees(roll)
        pitch_deg = math.degrees(pitch)
        
        self.create_text(10, 10, text=f"R: {roll_deg:.1f}°", anchor="nw", font=("Consolas", 10, "bold"), fill="white")
        self.create_text(self.width - 10, 10, text=f"P: {pitch_deg:.1f}°", anchor="ne", font=("Consolas", 10, "bold"), fill="white")
        
        # Level Indicator (Center Bottom)
        if abs(roll_deg) < 2 and abs(pitch_deg) < 2:
            self.create_text(self.center_x, self.height - 15, text="-- LEVEL --", anchor="center", font=("Arial", 10, "bold"), fill="#2ecc71")

        
        # Pitch Ladder (Simple Lines)
        # Drawn relative to the rotated horizon
        # For simplicity, just text overlays for now? No, simple ladder lines.
        # ... Omitted for brevity/performance in Tkinter, simple horizon is good.

class DroneApp(tk.Tk):
    def __init__(self, backend, mission_mgr):
        super().__init__()
        
        self.backend = backend
        self.mission_mgr = mission_mgr
        
        self.title("Drone Command Center 🚀")
        self.geometry("1400x900")
        self.minsize(800, 600) # prevent shrinking too much
        self.configure(bg=BG_COLOR)
        
        # Configure Grid - RESPONSIVE LAYOUT
        self.grid_columnconfigure(0, weight=0, minsize=320) # Sidebar Fixed Width (Corrected)
        self.grid_columnconfigure(1, weight=1)              # Map Expands to fill rest
        self.grid_rowconfigure(0, weight=3)                 # Map Row Dominant
        self.grid_rowconfigure(1, weight=1)                 # Log Row Smaller
        
        # Auto-Maximize on Start (Linux/Windows compatible attempt)
        try:
            # Linux (X11)
            self.attributes('-zoomed', True)
        except:
            try:
                # Windows
                self.state('zoomed')
            except:
                pass
        
        # Check for Fullscreen Toggle (F11)
        self.bind("<F11>", self.toggle_fullscreen)
        self.fullscreen_state = False
        
        # Styles
        self.setup_styles()
        
        # Load Drone Icon
        # Load Drone Icon
        try:
            # Try newer Pillow first, then fallback
            if hasattr(Image, 'Resampling'):
                resample = Image.Resampling.LANCZOS
            else:
                resample = Image.LANCZOS
            self.drone_icon_img = ImageTk.PhotoImage(Image.open("drone_icon.png").resize((40, 40), resample))
        except Exception as e:
            print(f"Warning: Could not load drone_icon.png: {e}")
            self.drone_icon_img = None

        self.marker_drone = None
        self.marker_home = None
        self.marker_gcs = None  # Laptop/Software Location
        self.centered_map = False
        self.centered_gcs = False # Track GCS centering
        self.trace_path = [] # History of (lat, lon)
        self.gcs_loc = None  # (lat, lon) for GCS
        self.wp_markers = [] # Store waypoint markers objects

        # Find GCS Location
        threading.Thread(target=self.fetch_gcs_location, daemon=True).start()
        
        # Layout
        self.create_sidebar()
        self.create_main_view()
        self.create_log_view()
        
        self.update_loop()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # General Frame Styles
        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("Sidebar.TFrame", background=SIDEBAR_COLOR)
        
        # Label Styles
        self.style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=("Arial", 10))
        self.style.configure("Sidebar.TLabel", background=SIDEBAR_COLOR, foreground=TEXT_COLOR)
        self.style.configure("Header.TLabel", background=SIDEBAR_COLOR, foreground=TEXT_COLOR, font=("Arial", 16, "bold"))
        self.style.configure("Status.TLabel", background=SIDEBAR_COLOR, foreground=TEXT_COLOR, font=("Consolas", 11))
        
        # LabelFrame
        self.style.configure("TLabelframe", background=SIDEBAR_COLOR, foreground=TEXT_COLOR, relief="solid")
        self.style.configure("TLabelframe.Label", background=SIDEBAR_COLOR, foreground=TEXT_COLOR)
        
        # Telemetry Box Style
        self.style.configure("Telemetry.TFrame", background="#222f3e", relief="sunken", borderwidth=2)
        self.style.configure("Telemetry.TLabel", background="#222f3e", foreground="#00d2d3", font=("Consolas", 12, "bold"))
        self.style.configure("TelemetryVal.TLabel", background="#222f3e", foreground="white", font=("Consolas", 12))
        
        # Buttons
        self.style.configure("TButton", font=("Arial", 10, "bold"), padding=8, borderwidth=0)
        self.style.map("TButton", background=[('active', '#555555')], foreground=[('active', 'white')])
        
        self.style.configure("Connect.TButton", background="#7f8c8d", foreground="white") # Grey
        # Styles for Buttons (Animatable via map)
        self.style.configure("Connect.TButton", font=("Arial", 10, "bold"), background="#2ecc71", foreground="white")
        self.style.map("Connect.TButton", background=[('active', '#27ae60'), ('pressed', '#219150')]) # Darker on press, Brighter on hover?
        # Actually standard map is: active=Hover, pressed=Click
        
        # Flight Control Styles (Vibrant & Animated)
        # Action (Blue)
        self.style.configure("Action.TButton", font=("Arial", 10, "bold"), background=BTN_ACTION, foreground="white")
        self.style.map("Action.TButton", background=[('active', '#3498db'), ('pressed', '#1abc9c')]) # Hover: Brighter Blue, Press: Teal
        
        # Warning (Orange)
        self.style.configure("Warn.TButton", font=("Arial", 10, "bold"), background=BTN_WARN, foreground="white")
        self.style.map("Warn.TButton", background=[('active', '#f39c12'), ('pressed', '#d35400')]) # Hover: Brighter Orange
        
        # Danger (Red)
        self.style.configure("Danger.TButton", font=("Arial", 10, "bold"), background=BTN_DANGER, foreground="white")
        self.style.map("Danger.TButton", background=[('active', '#e74c3c'), ('pressed', '#c0392b')]) # Hover: Lighter Red
        
        # EMERGENCY (Big & Bold)
        self.style.configure("Emergency.TButton", font=("Arial", 12, "bold"), background="#c0392b", foreground="white", padding=10)
        self.style.map("Emergency.TButton", background=[('active', '#ff0000'), ('pressed', '#8b0000')]) # Hover: Bright Red, Press: Dark Blood
        self.style.map("Success.TButton", background=[('disabled', '#2d5a2d')])
        self.style.map("Warn.TButton", background=[('disabled', '#5a4d2d')])
        self.style.map("Action.TButton", background=[('disabled', '#2d4d5a')])

        # HUD Styles (Vibrant & Animated)
        self.style.configure("HUD.TButton", background="#8e44ad", foreground="white", font=("Segoe UI", 9, "bold"), borderwidth=0)
        self.style.map("HUD.TButton",
            background=[('active', '#ff00ff'), ('disabled', '#2c3e50')],
            foreground=[('active', 'white'), ('disabled', '#7f8c8d')]
        )
        self.style.configure("HUDWarn.TButton", background="#c0392b", foreground="white", font=("Segoe UI", 9, "bold"))
        self.style.map("HUDWarn.TButton", background=[('active', '#ff3333')])

    def create_sidebar(self):
        # 1. Sidebar Container (Holds Canvas + Scrollbar)
        sidebar_container = ttk.Frame(self, style="Sidebar.TFrame", width=320)
        sidebar_container.grid(row=0, column=0, rowspan=2, sticky="nsew")
        
        # 2. Canvas & Scrollbar
        canvas = tk.Canvas(sidebar_container, bg=SIDEBAR_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(sidebar_container, orient="vertical", command=canvas.yview)
        
        # 3. Configure Scroll
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        # 4. Scrollable Frame (The "real" sidebar)
        self.sidebar = ttk.Frame(canvas, style="Sidebar.TFrame")
        
        # 5. Window in Canvas
        canvas_window = canvas.create_window((0, 0), window=self.sidebar, anchor="nw")
        
        # 6. Bindings for Resizing & Scrolling
        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            # Stretch inner frame to match canvas width
            canvas.itemconfig(canvas_window, width=event.width)
        
        def on_mousewheel(event):
            if canvas.winfo_exists():
                # Cross-platform scroll
                if event.num == 5 or event.delta < 0:
                     canvas.yview_scroll(1, "units")
                elif event.num == 4 or event.delta > 0:
                     canvas.yview_scroll(-1, "units")

        self.sidebar.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        
        # Helper: Recursively bind scroll events to widget and all children
        def _bind_to_widget_and_children(widget):
            # Linux
            widget.bind("<Button-4>", on_mousewheel)
            widget.bind("<Button-5>", on_mousewheel)
            # Windows/MacOS
            widget.bind("<MouseWheel>", on_mousewheel)
            
            for child in widget.winfo_children():
                _bind_to_widget_and_children(child)

        # Initial bind to container and canvas
        _bind_to_widget_and_children(sidebar_container)
        
        # IMPORTANT: When new widgets are added dynamically (like in sidebar), 
        # we need to re-bind or ensure they inherit. 
        # Since we pack everything into self.sidebar at init, we can just bind self.sidebar and children NOW.
        # But wait, self.sidebar children are added LATER in this function.
        # So we should call this helper AT THE END of this function.
        
        # Defer binding until after all widgets are added
        self.after(100, lambda: _bind_to_widget_and_children(self.sidebar))
        # Also bind the canvas itself immediately
        canvas.bind("<Button-4>", on_mousewheel)
        canvas.bind("<Button-5>", on_mousewheel)
        canvas.bind("<MouseWheel>", on_mousewheel)

        # Header
        ttk.Label(self.sidebar, text="COMMAND CENTER", style="Header.TLabel").pack(pady=(10,5))
        
        # CONNECTION (Compact)
        conn_frame = ttk.LabelFrame(self.sidebar, text="Connection", style="TLabelframe")
        conn_frame.pack(fill="x", padx=10, pady=5)
        
        self.entry_conn = ttk.Entry(conn_frame)
        self.entry_conn.pack(pady=2, fill="x", padx=5)
        self.entry_conn.insert(0, self.backend.connect_str)
        
        self.btn_connect = ttk.Button(conn_frame, text="CONNECT 🔌", style="Connect.TButton", command=self.toggle_connection)
        self.btn_connect.pack(pady=2, fill="x", padx=5)
        
        # === NEW: ARTIFICIAL HORIZON (AHRS) ===
        # Replaces Status box or sits above it
        self.ahrs = AHRSWidget(self.sidebar, height=180) # Width auto-fills
        self.ahrs.pack(pady=5, padx=10, fill="x")
        
        # Overlay Arm Text on AHRS
        self.lbl_ahrs_arm = self.ahrs.create_text(150, 90, text="DISARMED", font=("Arial", 24, "bold"), fill="red")
        
        # === FLIGHT CONTROLS (Moved to TOP Priority) ===
        ctrl_frame = ttk.LabelFrame(self.sidebar, text="Flight Controls", style="TLabelframe")
        ctrl_frame.pack(fill="x", padx=10, pady=5) # Top priority below AHRS
        
        # Force Arm Checkbox
        self.var_force = tk.BooleanVar()
        self.chk_force = tk.Checkbutton(ctrl_frame, text="Force", variable=self.var_force, bg=SIDEBAR_COLOR, fg="orange", selectcolor="#2c3e50", activebackground=SIDEBAR_COLOR, activeforeground="orange")
        self.chk_force.pack(anchor="ne", padx=5)
        
        self.btn_arm = ttk.Button(ctrl_frame, text="ARM 🛡️", style="Warn.TButton", command=lambda: self.backend.arm_disarm(True, force=self.var_force.get()), state="disabled")
        self.btn_arm.pack(fill="x", pady=2, padx=5)
        
        # DISARM: Force=True to reject all other commands and cut motors immediately
        self.btn_disarm = ttk.Button(ctrl_frame, text="DISARM 🔓", style="Danger.TButton", command=lambda: self.backend.arm_disarm(False, force=True), state="disabled")
        self.btn_disarm.pack(fill="x", pady=2, padx=5)
        
        ttk.Separator(ctrl_frame, orient="horizontal").pack(fill="x", pady=5)
        
        self.btn_takeoff = ttk.Button(ctrl_frame, text="TAKEOFF 🛫", style="Action.TButton", command=self.do_takeoff, state="disabled")
        self.btn_takeoff.pack(fill="x", pady=2, padx=5)
        
        self.btn_rtl = ttk.Button(ctrl_frame, text="RTL 🏠", style="Action.TButton", command=lambda: self.backend.set_mode("RTL"), state="disabled")
        self.btn_rtl.pack(fill="x", pady=2, padx=5)
        
        self.btn_land = ttk.Button(ctrl_frame, text="LAND 🛬", style="Action.TButton", command=lambda: self.backend.set_mode("LAND"), state="disabled")
        self.btn_land.pack(fill="x", pady=2, padx=5)

        ttk.Separator(ctrl_frame, orient="horizontal").pack(fill="x", pady=5)

        # Mode Selection
        mode_frame = ttk.Frame(ctrl_frame)
        mode_frame.pack(fill="x", padx=5, pady=2)
        ttk.Label(mode_frame, text="Mode:", style="Status.TLabel").pack(side="left")
        
        self.combo_mode = ttk.Combobox(mode_frame, values=["STABILIZE", "LOITER", "GUIDED", "RTL", "LAND", "AUTO", "BRAKE", "POSHOLD"], state="readonly", width=10)
        self.combo_mode.pack(side="left", padx=5)
        self.combo_mode.set("LOITER")
        
        self.btn_set_mode = ttk.Button(mode_frame, text="SET", width=4, style="Action.TButton", command=lambda: self.backend.set_mode(self.combo_mode.get()), state="disabled")
        self.btn_set_mode.pack(side="left", padx=2)
        
        # Takeoff Configuration (Altitude Input)
        frame_alt = ttk.Frame(ctrl_frame)
        frame_alt.pack(fill="x", pady=5, padx=5)
        
        ttk.Label(frame_alt, text="Alt (m):", style="Status.TLabel").pack(side="left")
        self.entry_alt = ttk.Entry(frame_alt, width=5)
        self.entry_alt.pack(side="left", padx=5)
        self.entry_alt.insert(0, "10") # Default 10m
        
        # STATUS (Valid for details)
        status_frame = ttk.LabelFrame(self.sidebar, text="Status", style="TLabelframe")
        status_frame.pack(fill="x", padx=10, pady=5)
        
        self.lbl_mode = ttk.Label(status_frame, text="Mode: UNKNOWN", style="Status.TLabel")
        self.lbl_mode.pack(anchor="w", padx=5, pady=2)

        self.lbl_arm = ttk.Label(status_frame, text="State: DISARMED", style="Status.TLabel", foreground="#e74c3c")
        self.lbl_arm.pack(anchor="w", padx=5, pady=2)
        
        self.lbl_bat = ttk.Label(status_frame, text="🔋 0.0V", style="Status.TLabel")
        self.lbl_bat.pack(anchor="w", padx=5, pady=2)
        
        self.lbl_gps = ttk.Label(status_frame, text="🛰️ No GPS", style="Status.TLabel")
        self.lbl_gps.pack(anchor="w", padx=5, pady=2)

        self.lbl_hdop = ttk.Label(status_frame, text="HDOP: --", style="Status.TLabel")
        self.lbl_hdop.pack(anchor="w", padx=5, pady=2)
        
        self.lbl_sys_status = ttk.Label(status_frame, text="System: WAIT", style="Status.TLabel", foreground="#f39c12")
        self.lbl_sys_status.pack(anchor="w", padx=5, pady=5)
        
        # TELEMETRY (Expandable)
        self.tele_frame = ttk.Frame(self.sidebar, style="Telemetry.TFrame", padding=10)
        self.tele_frame.pack(fill="x", padx=10, pady=5)
        
        tk.Label(self.tele_frame, text="TELEMETRY", bg="#222f3e", fg="#54a0ff", font=("Arial", 9, "bold")).pack(anchor="n", pady=5)
        
        # Grid Layout for Vals
        grid_frame = tk.Frame(self.tele_frame, bg="#222f3e")
        grid_frame.pack(fill="x")
        
        # Row 1: Dist / Speed
        tk.Label(grid_frame, text="DIST", bg="#222f3e", fg="#7f8c8d", font=("Arial", 8)).grid(row=0, column=0, sticky="w")
        self.lbl_dist = tk.Label(grid_frame, text="0.0m", bg="#222f3e", fg="white", font=("Consolas", 10, "bold"))
        self.lbl_dist.grid(row=0, column=1, sticky="w", padx=5)
        
        tk.Label(grid_frame, text="SPD", bg="#222f3e", fg="#7f8c8d", font=("Arial", 8)).grid(row=0, column=2, sticky="w")
        self.lbl_spd = tk.Label(grid_frame, text="0.0m/s", bg="#222f3e", fg="#00d2d3", font=("Consolas", 10, "bold"))
        self.lbl_spd.grid(row=0, column=3, sticky="w", padx=5)
        
        # Row 2: Alt / Climb
        tk.Label(grid_frame, text="ALT", bg="#222f3e", fg="#7f8c8d", font=("Arial", 8)).grid(row=1, column=0, sticky="w")
        self.lbl_alt = tk.Label(grid_frame, text="0.0m", bg="#222f3e", fg="white", font=("Consolas", 10, "bold"))
        self.lbl_alt.grid(row=1, column=1, sticky="w", padx=5)
        
        tk.Label(grid_frame, text="V.SPD", bg="#222f3e", fg="#7f8c8d", font=("Arial", 8)).grid(row=1, column=2, sticky="w")
        self.lbl_climb = tk.Label(grid_frame, text="0.0m/s", bg="#222f3e", fg="#00d2d3", font=("Consolas", 10, "bold"))
        self.lbl_climb.grid(row=1, column=3, sticky="w", padx=5)
        
        # Row 3: Fix
        tk.Label(grid_frame, text="FIX", bg="#222f3e", fg="#7f8c8d", font=("Arial", 8)).grid(row=2, column=0, sticky="w")
        self.lbl_fix = tk.Label(grid_frame, text="No Fix", bg="#222f3e", fg="red", font=("Consolas", 10, "bold"))
        self.lbl_fix.grid(row=2, column=1, columnspan=3, sticky="w", padx=5)
        
        # Error Box (Used for triggering Emergency Overlay)
        self.lbl_error = tk.Label(self.tele_frame, text="", bg="black", fg="red", font=("Arial", 11, "bold"), wraplength=220)
        self.lbl_error.pack(fill="x", pady=5)
        
        # Smart Emergency (Bottom) - BIGGER & ANIMATED
        self.btn_smart_land = ttk.Button(self.sidebar, text="🚨 SMART EMERGENCY 🚨", style="Emergency.TButton", command=self.smart_stop)
        self.btn_smart_land.pack(fill="x", padx=10, pady=20, side="bottom", ipady=15) # ipady makes it taller/bigger

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
        
        # Styled Log Header (Terminal Title Bar Look)
        header_frame = tk.Frame(log_container, bg="#34495e", height=20)
        header_frame.pack(fill="x")
        tk.Label(header_frame, text=" SYSTEM CONSOLE >_ ", bg="#34495e", fg="#00d2d3", font=("Consolas", 9, "bold")).pack(side="left")
        
        # Log Text Box (Real Terminal Look: Black BG, Green Text)
        self.log_text = tk.Text(log_container, height=6, font=("Courier New", 10), bg="#000000", fg="#00ff00", insertbackground="white", bd=0, padx=8, pady=5)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.config(state='disabled') # Prevent user typing
        
        # Redirect Prints with Timestamp
        import sys
        import datetime
        # Redirect Prints with Timestamp (Thread-Safe)
        import sys
        import datetime
        import queue
        
        self.log_queue = queue.Queue()
        
        class Redirect:
            def __init__(self, q): 
                self.q = q
            def write(self, s):
                self.q.put(s)
            def flush(self): pass
            
        sys.stdout = Redirect(self.log_queue)
        
        # Start polling the queue
        self.poll_log_queue()
        print("Welcome to Drone Command Center 🚀 initialized.")

    def poll_log_queue(self):
        try:
            while True:
                s = self.log_queue.get_nowait()
                self.log_text.config(state='normal') # Unlock
                if s.strip(): # Only stamp lines with text
                    timestamp = datetime.datetime.now().strftime("[%H:%M:%S] ")
                    self.log_text.insert("end", timestamp + s)
                else:
                    self.log_text.insert("end", s)
                self.log_text.see("end")
                self.log_text.config(state='disabled') # Lock again
        except queue.Empty:
            pass
        self.after(100, self.poll_log_queue)
            


    def create_osd_stats(self):
        # On-Screen Display (OSD) Stats - EMBEDDED DIRECTLY ON MAP
        # Note: Tkinter labels have a background color. We use the dark theme color.
        
        # 1. Battery (Bottom Left - Anchor)
        self.osd_bat = tk.Label(self.map_view, text="🔋 -- V", font=("Arial", 16, "bold"), fg="yellow", bg="#2c3e50")
        self.osd_bat.place(relx=0.02, rely=0.98, anchor="sw")
        
        # 2. GPS (Just ABOVE Battery)
        self.osd_gps = tk.Label(self.map_view, text="NO GPS", font=("Arial", 16, "bold"), fg="red", bg="#2c3e50")
        self.osd_gps.place(relx=0.02, rely=0.93, anchor="sw")
        
        # 3. HDOP (Just RIGHT of Battery)
        self.osd_hdop = tk.Label(self.map_view, text="HDOP: --", font=("Arial", 16, "bold"), fg="#f39c12", bg="#2c3e50")
        self.osd_hdop.place(relx=0.15, rely=0.98, anchor="sw")
        
        # 4. Distance (Bottom Right)
        self.osd_dist = tk.Label(self.map_view, text="DIS: -- m", font=("Arial", 16, "bold"), fg="#00d2d3", bg="#2c3e50")
        self.osd_dist.place(relx=0.98, rely=0.98, anchor="se")
        
        # 5. Altitude (Just ABOVE Distance)
        self.osd_alt = tk.Label(self.map_view, text="ALT: -- m", font=("Arial", 16, "bold"), fg="white", bg="#2c3e50")
        self.osd_alt.place(relx=0.98, rely=0.93, anchor="se")
        
        # 6. Arm Status (Top Center)
        self.osd_arm = tk.Label(self.map_view, text="DISARMED", font=("Arial", 20, "bold"), fg="red", bg="#2c3e50")
        self.osd_arm.place(relx=0.5, rely=0.05, anchor="n")

        # 7. Status Text (Bottom Center)
        self.osd_status = tk.Label(self.map_view, text="", font=("Arial", 14, "bold"), fg="red", bg="#2c3e50")
        self.osd_status.place(relx=0.5, rely=0.90, anchor="s")

    def setup_overlay_window(self):
        self.create_osd_stats()
        
        # EMBEDDED FRAME (Mission Control)
        # We place it directly on top of the map_view widget
        
        # Container for the HUD
        self.overlay_frame = tk.Frame(self.map_view, bg="#2c3e50", highlightbackground="white", highlightthickness=1)
        self.overlay_frame.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)
        
        # Header
        tk.Label(self.overlay_frame, text="MISSION CONTROL", font=("Segoe UI", 10, "bold"), bg="#2c3e50", fg="#00d2d3").pack(pady=5, fill="x", padx=5)
        
        # Waypoint List
        self.wp_list = Listbox(self.overlay_frame, height=6, width=25, bg="#34495e", fg="#ecf0f1", bd=0, highlightthickness=0)
        self.wp_list.pack(pady=2, padx=5)
        
        # Buttons
        btn_frame = tk.Frame(self.overlay_frame, bg="#2c3e50")
        btn_frame.pack(fill="x", pady=2, padx=5)
        
        ttk.Button(btn_frame, text="Delete ❌", width=8, command=self.delete_selected_wp, style="HUDWarn.TButton").pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Clear 🗑️", width=8, command=self.clear_mission_verify, style="HUDWarn.TButton").pack(side="right", padx=2)
        
        # Initial Mission Upload Button
        self.btn_upload = ttk.Button(self.overlay_frame, text="Upload Mission 📤", command=self.upload_mission, style="HUD.TButton")
        self.btn_upload.pack(pady=5, padx=5, fill="x")
        
        self.btn_start = ttk.Button(self.overlay_frame, text="START GUIDED ▶️", command=self.start_mission, state="disabled", style="HUDSuccess.TButton")
        self.btn_start.pack(pady=5, padx=5, fill="x")

    def on_root_map(self, event):
        pass

    def on_root_unmap(self, event):
        pass
    
    def sync_mission_widget_pos(self, event=None):
        pass
            
    # --- ACTIONS ---
    
    def toggle_connection(self):
        if not self.backend.connected:
            # START CONNECTING
            self.backend.connect_str = self.entry_conn.get()
            self.backend.start()
            self.centered_map = False # Reset for new connection
            
            # UI Feedback
            self.btn_connect.config(text="Connecting... ⏳", state="disabled")
            self.entry_conn.config(state="disabled")
            
            # Start Polling
            self.connect_start_time = time.time()
            self.check_connection_loop()
        else:
            # DISCONNECT
            self.backend.stop()
            self.btn_connect.config(text="CONNECT 🔌", state="normal", style="Connect.TButton")
            self.entry_conn.config(state="normal")
            self.style.configure("Connect.TButton", background="#7f8c8d") # Reset Gray

    def check_connection_loop(self):
        if self.backend.connected:
            # SUCCESS
            self.btn_connect.config(text="Disconnect ❌", state="normal")
            self.style.configure("Connect.TButton", background=BTN_DANGER)
            # messagebox.showinfo("Success", "Drone Connected!") 
        elif time.time() - self.connect_start_time > 10: # 10s Timeout
            # FAIL
            self.backend.stop()
            self.btn_connect.config(text="CONNECT 🔌", state="normal")
            self.entry_conn.config(state="normal")
            messagebox.showerror("Error", "Connection Failed: Timeout")
        else:
            # KEEP POLLING
            self.after(500, self.check_connection_loop)

    def smart_stop(self):
        # Ascend 4m -> Hover 3s -> Land
        self.backend.smart_emergency_land()
            
    def add_wp(self, coords):
        lat, lon = coords
        self.mission_mgr.add_waypoint(lat, lon)
        self.update_map_path()
        print(f"Added WP: {lat:.5f}, {lon:.5f}")

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
            print(f"Deleted WP {idx}")
        else:
            messagebox.showinfo("Undo", "Select a waypoint to delete.")

    def clear_mission_verify(self):
        if messagebox.askyesno("Clear Mission", "Are you sure you want to clear all waypoints?"):
            self.clear_wps()

    def clear_wps(self):
        self.mission_mgr.clear_waypoints()
        self.update_map_path()
        print("Waypoints cleared.")
        
    def update_map_path(self):
        # Refresh Listbox
        self.wp_list.delete(0, 'end')
        
        # Clear ONLY Waypoint Markers
        for m in self.wp_markers:
            m.delete()
        self.wp_markers.clear()
        
        # Clear Path Lines (trace_path is separate)
        self.map_view.delete_all_path()
        
        # Re-draw Waypoints
        path_coords = []
        for i, (lat, lon) in enumerate(self.mission_mgr.waypoints):
            self.wp_list.insert('end', f"{i}: {lat:.5f}, {lon:.5f}")
            # Create marker and track it
            m = self.map_view.set_marker(lat, lon, text=str(i))
            self.wp_markers.append(m)
            path_coords.append((lat, lon))
            
        # Draw Mission Path (Blue Line)
        if len(path_coords) > 1:
            self.map_view.set_path(path_coords)
            
        # Re-draw Trace Path (Red Line) - logic for this is in update_loop but path object persists?
        # Actually set_path returns a path object. We handle trace_path in update_loop continuously.
        # But delete_all_path() removed it. Ideally we should redraw trace_path here too if we want to keep it.
        # For now, update_loop will redraw trace_path on next tick if logic allows.
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
            
        print(f"Starting Guided Mission with Alt: {alt}")
        # EXECUTE GUIDED MISSION (Python Driven)
        self.mission_mgr.execute_guided_mission(altitude=alt)
             
    def upload_mission(self):
        if self.mission_mgr.upload_mission():
            print("Mission Uploaded Successfully!")
        else:
            print("Mission Upload Failed.")

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
        # Update Status Labels
        s = self.backend.state
        
        if self.backend.connected:
            self.lbl_mode.config(text=f"Mode: {s['mode']}")
            
            # --- ARMING STATUS & BUTTONS ---
            is_armed = s['armed']
            is_ready = s['ready_to_arm']
            force_arm = self.var_force.get()
            
            # Map OSD Status
            if is_armed:
                self.osd_arm.config(text="ARMED ⚠️", fg="#e74c3c") # Red for Danger
                self.lbl_arm.config(text="State: ARMED", foreground="#e74c3c")
            elif is_ready:
                self.osd_arm.config(text="READY TO ARM ✅", fg="#2ecc71") # Green
                self.lbl_arm.config(text="State: READY", foreground="#2ecc71")
            else:
                self.osd_arm.config(text="NOT READY ⛔", fg="#f39c12") # Orange
                self.lbl_arm.config(text="State: NOT READY", foreground="#f39c12")

            # Show Error Text on Map if Not Ready
            if not is_ready and not is_armed:
                 # Show the specific PreArm error if available
                 err_msg = s['error'].replace("PreArm:", "").strip()
                 if err_msg:
                     self.osd_status.config(text=f"Check: {err_msg}")
                 else:
                     self.osd_status.config(text="Checking System...")
            else:
                 self.osd_status.config(text="")

            # Button States
            # ARM Button: Enabled if Ready (or Force) AND Not Armed
            if (is_ready or force_arm) and not is_armed:
                self.btn_arm.state(["!disabled"])
            else:
                self.btn_arm.state(["disabled"])
                
            # DISARM Button: Enabled if Armed
            if is_armed:
                self.btn_disarm.state(["!disabled"])
            else:
                self.btn_disarm.state(["disabled"])
                
            # Flight Controls: Enabled ONLY if Armed
            if is_armed:
                # Takeoff: Only allowed in GUIDED or LOITER (per User Request)
                if s['mode'] in ['GUIDED', 'LOITER']:
                     self.btn_takeoff.state(["!disabled"])
                else:
                     self.btn_takeoff.state(["disabled"])

                self.btn_rtl.state(["!disabled"])
                self.btn_land.state(["!disabled"])
                self.btn_set_mode.state(["!disabled"])
                self.btn_start.state(["!disabled"]) # Guided Mission Start
            else:
                self.btn_takeoff.state(["disabled"])
                self.btn_rtl.state(["disabled"])
                self.btn_land.state(["disabled"])
                self.btn_set_mode.state(["disabled"])
                self.btn_start.state(["disabled"])

            self.lbl_bat.config(text=f"🔋 {s['voltage']:.1f}V")
            
            # --- HDOP & GPS Readiness Logic ---
            hdop = s['gps_hdop']
            fix_type = s['gps_fix']
            
            self.lbl_hdop.config(text=f"HDOP: {hdop:.2f}")
            
            # Criteria: 3D Fix (>=3) AND HDOP < 2.0 OR ArduPilot says Ready
            # We defer to ArduPilot 'ready_to_arm' for the main status, 
            # but keep GPS text updated.
            gps_ok = (fix_type >= 3 and hdop < 2.0)
            
            if gps_ok:
                self.lbl_gps.config(text=f"🛰️ GPS LOCK (3D)", foreground="#2ecc71") # Green
            elif fix_type < 2:
                self.lbl_gps.config(text="🛰️ Waiting for GPS", foreground="#e74c3c") # Red
            else:
                self.lbl_gps.config(text=f"🛰️ 3D Fix (High HDOP)", foreground="#f39c12") # Orange

            # --- OSD Telemetry Updates (Map) ---
            # 1. Battery
            self.osd_bat.config(text=f"🔋 {s['voltage']:.1f} V")
            
            # 2. GPS
            if s['gps_fix'] >= 3:
                 self.osd_gps.config(text=f"GPS LOCK ({s['gps_sats']})", fg="#2ecc71")
            else:
                 self.osd_gps.config(text="NO GPS", fg="#e74c3c")
                 
            # 3. HDOP
            self.osd_hdop.config(text=f"HDOP: {s['gps_hdop']:.1f}")
            
            # 4. Dist & Alt
            self.osd_dist.config(text=f"DIS: {s['dist_home']:.1f}m")
            self.osd_alt.config(text=f"ALT: {s['alt_rel']:.1f}m")

            # --- Readiness Logic (ArduPilot Strict) ---
            status_msg = s.get('status_text', '')
            is_prearm_error = "PreArm" in status_msg or "error" in status_msg.lower()
            
            if s['armed']:
                 self.lbl_sys_status.config(text="ARMED / FLYING ✈️", foreground="#e74c3c") # Red (Danger)
            elif is_prearm_error:
                 self.lbl_sys_status.config(text="PRE-ARM ERROR ⚠️", foreground="#e74c3c")
            elif s['system_status'] == 3: # MAV_STATE_STANDBY
                 if gps_ok:
                     self.lbl_sys_status.config(text="READY TO ARM ✅", foreground="#2ecc71")
                 else:
                     self.lbl_sys_status.config(text="WAIT FOR GPS ⏳", foreground="#f39c12")
            else:
                 self.lbl_sys_status.config(text="NOT READY ❌", foreground="#e74c3c")

            # --- System Status & AHRS ---
            
            # AHRS Update
            self.ahrs.draw_horizon(s['roll'], s['pitch'])
            
            # Update Arm Status on AHRS
            ahrs_txt = "ARMED" if is_armed else ("READY" if is_ready else "DISARMED")
            ahrs_col = "red" if is_armed else ("green" if is_ready else "white")
            self.ahrs.itemconfig(self.lbl_ahrs_arm, text=ahrs_txt, fill=ahrs_col)

            # --- Telemetry Box Updates ---
            
            # --- Sidebar Telemetry Updates (Restored) ---
            self.lbl_dist.config(text=f"{s['dist_home']:.1f}m")
            self.lbl_spd.config(text=f"{s['speed']:.1f}m/s")
            self.lbl_alt.config(text=f"{s['alt_rel']:.1f}m")
            self.lbl_climb.config(text=f"{s['climb']:.1f}m/s")
            self.lbl_fix.config(text=s['gps_string'])

            # --- Telemetry Box Updates (Map OSD handled below) ---
            
            # Error Handling & Emergency Overlay
            # User request: "removed left corner on top in red" (Emergency Overlay)
            # Only show for CRITICAL IN-FLIGHT failures, NOT PreArm checks.
            critical_error = False
            if s['error']:
                # Show in sidebar box always
                self.lbl_error.config(text=f"⚠️ {s['error']}", bg="red", fg="white")
                
                # Check directly if it's a PreArm error to suppress the fullscreen flash
                if "PreArm" in s['error']:
                     critical_error = False
                else:
                     critical_error = True
            elif not gps_ok and s['armed'] and s['mode'] in ['GUIDED', 'AUTO']:
                # Critical Safety Warning (Armed without GPS in auto modes)
                critical_error = True
                self.lbl_error.config(text="UNSAFE: ARMED NO GPS", bg="red", fg="white")
            else:
                self.lbl_error.config(text="", bg="black", fg="red")
                critical_error = False
            
            # Flash only if CRITICAL
            if critical_error:
                 self.flash_emergency(True, msg=s['error'] or "CRITICAL ALERT")
            else:
                 self.flash_emergency(False)
            
            # --- Drone Marker ---
            if s['lat'] != 0 and s['lon'] != 0:
                if self.marker_drone is None:
                    # Create Marker with Icon if available
                    if self.drone_icon_img:
                        self.marker_drone = self.map_view.set_marker(s['lat'], s['lon'], icon=self.drone_icon_img)
                    else:
                        self.marker_drone = self.map_view.set_marker(s['lat'], s['lon'], text="🚁")
                else:
                    self.marker_drone.set_position(s['lat'], s['lon'])
                    
                # Auto-Center on first valid fix
                if not self.centered_map:
                    self.map_view.set_position(s['lat'], s['lon'])
                    self.map_view.set_zoom(18) # Zoom in for better view
                    self.centered_map = True
                    print(f"Drone GPS Locked: {s['lat']}, {s['lon']} (Map Centered)")

                # --- Path Tracing REMOVED per user request ---
                # Code removed to stop drawing red line

            elif self.backend.connected and not self.centered_map:
                # Connected but no GPS fix yet
                pass

            # --- Home Marker (Drone Launch Point) ---
            if s['home_lat'] and s['home_lon']:
                if self.marker_home is None:
                    # Renamed to "LAUNCH" to distinguish from Laptop "HOME"
                    self.marker_home = self.map_view.set_marker(s['home_lat'], s['home_lon'], text="🚩 Launch", marker_color_circle="yellow", marker_color_outside="red")
                else:
                    self.marker_home.set_position(s['home_lat'], s['home_lon'])
            
            # --- Cursor Logic ---
            # Set cursor based on connection
            cursor_type = "hand2" # Hand
            self.configure(cursor="") # Reset default
            for btn in [self.btn_arm, self.btn_disarm, self.btn_takeoff, self.btn_rtl, self.btn_land, self.btn_start]:
                btn.config(cursor=cursor_type)
                
            # Enable buttons (Connected)
            # Enable buttons (Connected)
            # Default State for most buttons
            all_flight_btns = [
                self.btn_arm, 
                self.btn_takeoff, self.btn_rtl, self.btn_land, 
                self.btn_start, self.btn_set_mode
            ]
            
            # STRICT SAFETY LOGIC REMOVED per user request
            # Enable buttons if Connected
            can_control = self.backend.connected
            
            for btn in all_flight_btns:
                 if can_control:
                      btn.config(state="normal")
                 else:
                      btn.config(state="disabled")

            # ALWAYS ENABLE DISARM IF CONNECTED (Priority)
            if self.backend.connected:
                self.btn_disarm.config(state="normal", cursor="hand2")
            else:
                self.btn_disarm.config(state="disabled", cursor="X_cursor")

            # Cursor Logic
            if can_control:
                cursor_type = "hand2"
            else:
                cursor_type = "X_cursor" # or "arrow"
            
            for btn in all_flight_btns:
                btn.config(cursor=cursor_type)
                
            # AUTO MODE SAFETY LOCK
            # If in AUTO, disable Disconnect to prevent accidents
            if s['mode'] == 'AUTO' or s['mode'] == 'GUIDED': # Guided also dangerous to disconnect
                 self.btn_connect.config(state="disabled", cursor="X_cursor")
            elif self.backend.connected: # Restore if just connected and not auto
                 self.btn_connect.config(state="normal", cursor="")
                 
        else:
            self.lbl_mode.config(text="Mode: --")
            
            # FORCE LOGIC: If Force is checked, enable buttons anyway
            if self.var_force.get():
                cursor_type = "hand2"
                for btn in [self.btn_arm, self.btn_disarm, self.btn_takeoff, self.btn_rtl, self.btn_land, self.btn_start]:
                    btn.config(state="normal", cursor=cursor_type)
            else:
                cursor_type = "pirate" # Skull/Crossbones or X_cursor
                for btn in [self.btn_arm, self.btn_disarm, self.btn_takeoff, self.btn_rtl, self.btn_land, self.btn_start]:
                   btn.config(state="disabled", cursor="X_cursor")

        # --- GCS/Laptop Marker & Auto-Focus (RUNS ALWAYS) ---
        if self.gcs_loc:
            if self.marker_gcs is None:
                print(f"GCS Location Acquired: {self.gcs_loc}")
                # User requested this to be denoted with "HOME" symbol
                self.marker_gcs = self.map_view.set_marker(self.gcs_loc[0], self.gcs_loc[1], text="🏠 HOME", marker_color_circle="blue", marker_color_outside="cyan")
            
            # Auto-Center on GCS (if Drone not yet centered/connected)
            if not self.centered_gcs and not self.centered_map:
                self.map_view.set_position(self.gcs_loc[0], self.gcs_loc[1])
                self.map_view.set_zoom(14)
                self.centered_gcs = True
                print("Map centered on GCS Location.")

        # Continuous visual sync for overlay to prevent lag
        self.sync_mission_widget_pos()
            
        self.after(100, self.update_loop)


