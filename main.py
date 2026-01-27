#!/usr/bin/env python3
from backend import DroneBackend
from mission import MissionManager
from gui import DroneApp
import faulthandler
faulthandler.enable()

def main():
    # 1. Initialize GUI
    # Delegate backend and mission management to the App
    app = DroneApp()
    
    # 2. Start Application
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()

if __name__ == "__main__":
    main()
