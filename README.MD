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

Configure the command-line flags in `lenovo-ec.service` before installing it:
- `--temp-on` / `--temp-off`: enter/leave Extreme Cooling (defaults: 70/60°C).
- `--temp-normal-on` / `--temp-normal-off`: enter normal mode/turn fans off (defaults: 50/40°C).
- `--interval`: seconds between temperature checks (default: 5; must be positive).

Thresholds must satisfy `temp-normal-off < temp-normal-on <= temp-off < temp-on`.
Normal mode stays active until `temp-normal-off`, including when stepping down
from Extreme Cooling. This hysteresis prevents switching on every small fluctuation.

## 2) Install and start the systemd service

Copy `lenovo-ec.service` to `/etc/systemd/system/`, then reload and enable it:

```bash
sudo cp lenovo-ec.service /etc/systemd/system/lenovo-ec.service
sudo systemctl daemon-reload
sudo systemctl enable --now lenovo-ec.service
```

After updating an existing installation, repeat the copy commands, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart lenovo-ec.service
```

## Behavior and troubleshooting

- The first temperature sample explicitly sets a fan mode, even when it selects OFF.
- A missing sensor at startup waits and does not command the EC. The wait is
  logged immediately and then once a minute until a reading arrives.
- If temperature reads fail after a good sample, the controller requests EXTREME
  cooling and rediscovers the sensor on subsequent checks. That failure is logged
  immediately and then once a minute. Normal hysteresis resumes when readings recover.
- Failed EC writes are logged and retried on the next temperature check. A successful
  write means the EC consumed the command; it does not verify physical fan speed.
- SIGINT/SIGTERM wake the controller immediately; shutdown attempts to set OFF.
- A kernel lock prevents concurrent instances. `/run/auto_ec.pid` stays in place,
  but its lock is released automatically when the process exits.

View recent mode changes and errors:

```bash
journalctl -u lenovo-ec.service -n 100 --no-pager
```

Repeated NORMAL/OFF changes at 50°C/40°C match the default thresholds: the CPU
warms while fans are off, then cools while they run. Lowering `--temp-normal-off`
keeps normal mode active longer. Repeated EC errors or fans disagreeing with logged
modes need further diagnosis; this script tracks the last successfully written mode
and does not read back the register or fan RPM.

## Development checks

The regression tests use simulated EC I/O and temporary sensor files:

```bash
python3 -m unittest discover -s tests -v
systemd-analyze verify lenovo-ec.service
```

## Compatibility notes

- `auto_ec.py` reads temperatures from `k10temp`, so it is mainly compatible with systems exposing that sensor name (commonly AMD). On systems with different sensor names, it may not detect CPU temperature.
- `auto_ec.py` writes to `/dev/port`, so it needs root privileges (handled by the systemd service when started by systemd as root).

## License

This project is licensed under **GNU GPL v3.0 or later** (`GPL-3.0-or-later`).
See `LICENSE` for the full license text.
