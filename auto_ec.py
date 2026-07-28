#!/usr/bin/python3
import argparse
import atexit
import os
import glob
import signal
import sys
import time

# EC address constants (from Alberto Vicente/ExtremeCooling4Linux)
EC_SC = 0x66
EC_DATA = 0x62
IBF = 1   # Input Buffer Full bit in EC status register
OBF = 0   # Output Buffer Full bit in EC status register
RD_EC = 0x80
WR_EC = 0x81
EXTREME_COOLING_REGISTER = 0xBD
ACTIVATE = 0x40
DEACTIVATE = 0x00

DEFAULT_TEMP_ON = 70
DEFAULT_TEMP_OFF = 60
DEFAULT_INTERVAL = 5

PID_FILE = "/run/auto_ec.pid"

# Module-level state for signal handler access
_port_fd = None
_temp_fd = None
_shutdown = False
_is_active = False


def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_cpu_temp_path():
    for path in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            with open(path, "r") as f:
                if "k10temp" in f.read():
                    return path.replace("name", "temp1_input")
        except OSError:
            continue
    return None


def ec_wait(fd, bit, value):
    for _ in range(100):
        try:
            buf = os.pread(fd, 1, EC_SC)
            if not buf:
                time.sleep(0.001)
                continue
            status = buf[0]
        except OSError:
            time.sleep(0.001)
            continue
        if ((status >> bit) & 0x1) == value:
            return True
        time.sleep(0.001)
    return False


def ec_write(fd, port, value):
    if not ec_wait(fd, IBF, 0):
        return False
    os.pwrite(fd, bytes([WR_EC]), EC_SC)
    if not ec_wait(fd, IBF, 0):
        return False
    os.pwrite(fd, bytes([port]), EC_DATA)
    if not ec_wait(fd, IBF, 0):
        return False
    os.pwrite(fd, bytes([value]), EC_DATA)
    return True


def cleanup_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def handle_signal(signum, frame):
    global _shutdown
    sig_name = signal.Signals(signum).name
    log(f"Received {sig_name}, shutting down...")
    _shutdown = True


def write_pid():
    try:
        with open(PID_FILE, "x") as f:
            f.write(str(os.getpid()))
    except FileExistsError:
        try:
            with open(PID_FILE, "r") as f:
                old_pid = f.read().strip()
            os.kill(int(old_pid), 0)
            log(f"Another instance is already running (PID {old_pid})")
            sys.exit(1)
        except (ProcessLookupError, ValueError, PermissionError):
            with open(PID_FILE, "w") as f:
                f.write(str(os.getpid()))
    atexit.register(cleanup_pid)


def main():
    global _port_fd, _temp_fd, _is_active

    parser = argparse.ArgumentParser(description="Lenovo Extreme Cooling Automation")
    parser.add_argument("--temp-on", type=int, default=DEFAULT_TEMP_ON,
                        help=f"Temperature threshold to activate (default: {DEFAULT_TEMP_ON})")
    parser.add_argument("--temp-off", type=int, default=DEFAULT_TEMP_OFF,
                        help=f"Temperature threshold to deactivate (default: {DEFAULT_TEMP_OFF})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Temperature check interval in seconds (default: {DEFAULT_INTERVAL})")
    args = parser.parse_args()

    # Hysteresis: 10°C gap between on/off prevents rapid toggling
    # when temperature fluctuates around the threshold.
    if args.temp_off >= args.temp_on:
        log("--temp-off must be less than --temp-on")
        sys.exit(1)

    write_pid()

    temp_path = get_cpu_temp_path()
    if not temp_path:
        log("CPU temperature sensor (k10temp) not found")
        sys.exit(1)

    if not os.access("/dev/port", os.R_OK | os.W_OK):
        log("No read/write access to /dev/port — run as root")
        sys.exit(1)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    _port_fd = os.open("/dev/port", os.O_RDWR)
    _temp_fd = os.open(temp_path, os.O_RDONLY)

    log(f"Started: temp_on={args.temp_on}°C temp_off={args.temp_off}°C interval={args.interval}s")

    try:
        _is_active = False
        while not _shutdown:
            try:
                raw = os.pread(_temp_fd, 16, 0)
                if isinstance(raw, bytes):
                    raw = raw.decode("ascii", errors="ignore").strip()
                temp = int(raw) / 1000
            except (OSError, ValueError, AttributeError):
                temp = 0
                log(f"Failed to read temperature from {temp_path}")

            try:
                if temp >= args.temp_on and not _is_active:
                    if ec_write(_port_fd, EXTREME_COOLING_REGISTER, ACTIVATE):
                        _is_active = True
                        log(f"Extreme Cooling ON (temp={temp}°C)")
                    else:
                        log("EC write timeout — failed to activate Extreme Cooling")
                elif temp <= args.temp_off and _is_active:
                    if ec_write(_port_fd, EXTREME_COOLING_REGISTER, DEACTIVATE):
                        _is_active = False
                        log(f"Extreme Cooling OFF (temp={temp}°C)")
                    else:
                        log("EC write timeout — failed to deactivate Extreme Cooling")
            except (OSError, IndexError) as e:
                log(f"EC communication error: {e}")

            time.sleep(args.interval)
    finally:
        if _is_active:
            log("Deactivating Extreme Cooling before exit...")
            if ec_write(_port_fd, EXTREME_COOLING_REGISTER, DEACTIVATE):
                _is_active = False
                log("Extreme Cooling deactivated")
            else:
                log("EC write timeout — Extreme Cooling may still be active")
        os.close(_temp_fd)
        os.close(_port_fd)
        log("Stopped")


if __name__ == "__main__":
    main()
