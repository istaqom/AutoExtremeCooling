# Auto Extreme Cooling

Inspired by Alberto Vicente's **ExtremeCooling4Linux**: https://gitlab.com/OdinTdh/extremecooling4linux

Tested working on **Lenovo Ideapad Gaming 3 15ARH05**.
Developed on **Bazzite** with **Python 3.14.3**.

This project is created because my laptop Extreme Cooling was not working correctly in Bazzite and caused overheating, and because I often forgot to turn ExtremeCooling4Linux on or off manually.

This project has:
- `auto_ec.py`: background script that toggles Lenovo Extreme Cooling based on CPU temperature.
- `lenovo-ec.service`: systemd service to run `auto_ec.py` at boot.
- `ec_tray.py`: optional tray indicator app for desktop sessions.

## 1) Install `auto_ec.py`

Copy `auto_ec.py` to `/usr/local/bin/`, then make it executable with `755` permission:

```bash
sudo cp auto_ec.py /usr/local/bin/auto_ec.py
sudo chmod 755 /usr/local/bin/auto_ec.py
```

You can modify `auto_ec.py` before copying it (or edit `/usr/local/bin/auto_ec.py` later), especially:
- `TEMP_ON` and `TEMP_OFF` to tune when Extreme Cooling turns on/off.
- `INTERVAL` to tune how often temperature checks run.

## 2) Install and start the systemd service

Copy `lenovo-ec.service` to `/etc/systemd/system/`, then reload and enable it:

```bash
sudo cp lenovo-ec.service /etc/systemd/system/lenovo-ec.service
sudo systemctl daemon-reload
sudo systemctl enable --now lenovo-ec.service
```

## 3) Install `ec_tray.py` and autostart it

`ec_tray.py` needs `PyQt6`. Install it first:

```bash
python3 -m pip install --user PyQt6
```

You can place `ec_tray.py` anywhere you want (for example `~/Apps/ec_tray.py`), then make it executable:

```bash
chmod 755 /path/to/ec_tray.py
```

To autostart in most desktop environments, create a desktop entry:

```bash
mkdir -p ~/.config/autostart
```

Create `~/.config/autostart/ec_tray.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Extreme Cooling Tray
Exec=/path/to/ec_tray.py
Terminal=false
X-GNOME-Autostart-enabled=true
```

Replace `/path/to/ec_tray.py` with your real path.

## Desktop environment and compatibility notes

- `auto_ec.py` reads temperatures from `k10temp`, so it is mainly compatible with systems exposing that sensor name (commonly AMD). On systems with different sensor names, it may not detect CPU temperature.
- `auto_ec.py` writes to `/dev/port`, so it needs root privileges (handled by the systemd service when started by systemd as root).
- `ec_tray.py` depends on `PyQt6` and `QSystemTrayIcon`. Some desktop environments (especially GNOME defaults without AppIndicator extensions) may not show tray icons correctly.
- On Wayland sessions, tray icon behavior depends on compositor and desktop support; X11 sessions are usually more consistent for legacy tray indicators.
- Icon themes may vary, so `temperature-cold` / `temperature-warm` theme icons might not exist in all themes.

## License

This project is licensed under **GNU GPL v3.0 or later** (`GPL-3.0-or-later`).
See `LICENSE` for the full license text.
