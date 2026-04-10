#!/usr/bin/python3
import sys, os
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer

class FanTrayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        
        self.icon_on = QIcon.fromTheme("temperature-cold") 
        self.icon_off = QIcon.fromTheme("temperature-warm")
        
        self.tray = QSystemTrayIcon(self.icon_off, self.app)
        
        menu = QMenu()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.app.quit)
        self.tray.setContextMenu(menu)
        
        self.tray.show()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(2000)

    def update_ui(self):
        status = "OFF"
        status_file = "/tmp/ec_fan_status"
        
        if os.path.exists(status_file):
            try:
                with open(status_file, "r") as f:
                    status = f.read().strip()
            except Exception as e:
                print(f"Read error: {e}")
        
        if status == "ON":
            self.tray.setIcon(self.icon_on)
            self.tray.setToolTip("Extreme Cooling: ACTIVE")
        else:
            self.tray.setIcon(self.icon_off)
            self.tray.setToolTip("Extreme Cooling: OFF")

if __name__ == "__main__":
    tray_app = FanTrayApp()
    sys.exit(tray_app.app.exec())
