# Auto Extreme Cooling

Inspired by Alberto Vicente's **ExtremeCooling4Linux**: https://gitlab.com/OdinTdh/extremecooling4linux

Tested working on **Lenovo Ideapad Gaming 3 15ARH05**.
Developed on **Bazzite** with **Python 3.14.3**.

This project is created because my laptop Extreme Cooling was not working correctly in Bazzite and caused overheating, and because I often forgot to turn ExtremeCooling4Linux on or off manually.

This project has:
- `auto_ec.py`: background script that sets Lenovo fan mode from CPU temperature: off (`0x00`), normal (`0x80`), or Extreme Cooling (`0x40`).
- `lenovo-ec.service`: systemd service to run `auto_ec.py` at boot.

## 1) Install `auto_ec.py`

Copy `auto_ec.py` to `/usr/local/bin/`, then make it executable with `755` permission:

```bash
sudo cp auto_ec.py /usr/local/bin/auto_ec.py
sudo chmod 755 /usr/local/bin/auto_ec.py
```

You can modify `auto_ec.py` before copying it (or edit `/usr/local/bin/auto_ec.py` later), especially:
- `TEMP_ON` / `TEMP_OFF` to tune when Extreme Cooling (`0x40`) turns on/off.
- `TEMP_NORMAL_ON` / `TEMP_NORMAL_OFF` to tune when normal fan (`0x80`) turns on/off.
- `INTERVAL` to tune how often temperature checks run.

## 2) Install and start the systemd service

Copy `lenovo-ec.service` to `/etc/systemd/system/`, then reload and enable it:

```bash
sudo cp lenovo-ec.service /etc/systemd/system/lenovo-ec.service
sudo systemctl daemon-reload
sudo systemctl enable --now lenovo-ec.service
```

## Compatibility notes

- `auto_ec.py` reads temperatures from `k10temp`, so it is mainly compatible with systems exposing that sensor name (commonly AMD). On systems with different sensor names, it may not detect CPU temperature.
- `auto_ec.py` writes to `/dev/port`, so it needs root privileges (handled by the systemd service when started by systemd as root).

## License

This project is licensed under **GNU GPL v3.0 or later** (`GPL-3.0-or-later`).
See `LICENSE` for the full license text.
