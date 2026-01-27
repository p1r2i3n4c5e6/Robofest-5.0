#!/usr/bin/env python3
from backend import DroneBackend
from mission import MissionManager
from gui import DroneApp

def main():
    # 1. Initialize Backend
    backend = DroneBackend()
    
    # 2. Initialize Mission Manager
    mission_mgr = MissionManager(backend)
    
    # 3. Initialize GUI
    app = DroneApp(backend, mission_mgr)
    
    # 4. Start Application
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        backend.stop()

if __name__ == "__main__":
    main()
