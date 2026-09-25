#!/usr/bin/python3
import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import glob
import os
import select
import signal
import sys
import threading
import time

# EC address constants (from Alberto Vicente/ExtremeCooling4Linux)
EC_SC = 0x66
EC_DATA = 0x62
IBF = 1   # Input Buffer Full bit in EC status register
WR_EC = 0x81
EXTREME_COOLING_REGISTER = 0xBD
MODE_OFF = 0x00
MODE_NORMAL = 0x80
MODE_EXTREME = 0x40
MODE_NAMES = {
    MODE_OFF: "OFF",
    MODE_NORMAL: "NORMAL",
    MODE_EXTREME: "EXTREME",
}

DEFAULT_TEMP_ON = 70
DEFAULT_TEMP_OFF = 60
DEFAULT_TEMP_NORMAL_ON = 50
DEFAULT_TEMP_NORMAL_OFF = 40
DEFAULT_INTERVAL = 5

PID_FILE = "/run/auto_ec.pid"
EC_TIMEOUT = 0.1
EC_POLL_INTERVAL = 0.001
FAIL_LOG_INTERVAL = 60


def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_cpu_temp_path():
    for path in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
        try:
            with open(path, "r") as f:
                if f.read().strip() != "k10temp":
                    continue
            temp_path = os.path.join(os.path.dirname(path), "temp1_input")
            if os.path.isfile(temp_path):
                return temp_path
        except OSError:
            continue
    return None


class TemperatureSensor:
    def __init__(self):
        self.path = get_cpu_temp_path()

    def read(self):
        if self.path is None:
            self.path = get_cpu_temp_path()
        if self.path is None:
            raise OSError("CPU temperature sensor (k10temp) not found")
        try:
            # Reopen sysfs each time so a stale descriptor cannot survive resume.
            with open(self.path, "rb") as f:
                return int(f.read()) / 1000
        except (OSError, ValueError):
            # hwmon numbering can change when a sensor disappears/reappears.
            self.path = None
            raise


def ec_wait(fd, bit, value):
    deadline = time.monotonic() + EC_TIMEOUT
    while True:
        buf = os.pread(fd, 1, EC_SC)
        if len(buf) != 1:
            raise OSError("Short read from EC status register")
        if ((buf[0] >> bit) & 0x1) == value:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"EC timeout waiting for status bit {bit}={value}")
        time.sleep(EC_POLL_INTERVAL)


def ec_write(fd, port, value):
    for address, byte in ((EC_SC, WR_EC), (EC_DATA, port), (EC_DATA, value)):
        ec_wait(fd, IBF, 0)
        if os.pwrite(fd, bytes([byte]), address) != 1:
            raise OSError(f"Short write to EC port {address:#x}")
    # Do not cache a mode until the EC has consumed the final data byte.
    ec_wait(fd, IBF, 0)


def choose_mode(mode, temp, thresholds):
    """Choose a mode using hysteresis; None temperature means sensor failure."""
    if temp is None or temp >= thresholds.temp_on:
        return MODE_EXTREME
    if mode == MODE_EXTREME and temp > thresholds.temp_off:
        return MODE_EXTREME
    if temp <= thresholds.temp_normal_off:
        return MODE_OFF
    if mode in (MODE_NORMAL, MODE_EXTREME) or temp >= thresholds.temp_normal_on:
        return MODE_NORMAL
    return MODE_OFF


class FanController:
    def __init__(self, fd):
        self.fd = fd
        # Unknown at startup: explicitly apply the first selected mode.
        self.mode = None
        self.write_failed = False

    def set_mode(self, mode, reason):
        if mode == self.mode and not self.write_failed:
            return True
        try:
            ec_write(self.fd, EXTREME_COOLING_REGISTER, mode)
        except OSError as e:
            # A partial transaction may have changed the hardware. Reapply the
            # next selection even if it matches the last successful mode.
            self.write_failed = True
            log(f"EC communication error setting {MODE_NAMES[mode]}: {e}")
            return False
        self.mode = mode
        self.write_failed = False
        log(f"Fan {MODE_NAMES[mode]} ({reason})")
        return True

    def stop(self):
        if not self.set_mode(MODE_OFF, "shutdown"):
            log("Could not reset fan mode before exit")


@contextmanager
def single_instance(path=PID_FILE):
    # Keep this file in place: unlinking a locked file permits two processes
    # to lock different inodes. The kernel releases the lock even after a crash.
    with open(path, "a+", encoding="ascii") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError("Another auto_ec instance is already running") from e
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
        yield


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Lenovo Extreme Cooling Automation")
    parser.add_argument("--temp-on", type=int, default=DEFAULT_TEMP_ON,
                        help=f"Temperature threshold to activate extreme cooling (default: {DEFAULT_TEMP_ON})")
    parser.add_argument("--temp-off", type=int, default=DEFAULT_TEMP_OFF,
                        help=f"Temperature threshold to leave extreme cooling (default: {DEFAULT_TEMP_OFF})")
    parser.add_argument("--temp-normal-on", type=int, default=DEFAULT_TEMP_NORMAL_ON,
                        help=f"Temperature threshold to activate normal fan (default: {DEFAULT_TEMP_NORMAL_ON})")
    parser.add_argument("--temp-normal-off", type=int, default=DEFAULT_TEMP_NORMAL_OFF,
                        help=f"Temperature threshold to turn fans off (default: {DEFAULT_TEMP_NORMAL_OFF})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Temperature check interval in seconds (default: {DEFAULT_INTERVAL})")
    args = parser.parse_args(argv)
    if not (args.temp_normal_off < args.temp_normal_on <= args.temp_off < args.temp_on):
        parser.error("thresholds must satisfy: --temp-normal-off < --temp-normal-on "
                     "<= --temp-off < --temp-on")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    return args


class StopSignal:
    """Wake a poll from SIGINT/SIGTERM via a non-blocking pipe."""

    def __init__(self):
        self._flag = threading.Event()
        self._read, self._write = os.pipe()
        os.set_blocking(self._read, False)
        os.set_blocking(self._write, False)

    def install_wakeup(self):
        return signal.set_wakeup_fd(self._write)

    def close(self):
        for fd in (self._read, self._write):
            try:
                os.close(fd)
            except OSError:
                pass
        self._read = self._write = None

    def set(self):
        self._flag.set()

    def is_set(self):
        return self._flag.is_set()

    def wait(self, timeout):
        if self._flag.is_set():
            return True
        readable, _, _ = select.select([self._read], [], [], timeout)
        if readable:
            try:
                while os.read(self._read, 256):
                    pass
            except (BlockingIOError, OSError):
                pass
        return self._flag.is_set()


def _log_sensor_failure(message, last_fail_log):
    now = time.monotonic()
    if last_fail_log is not None and now - last_fail_log < FAIL_LOG_INTERVAL:
        return last_fail_log
    log(message)
    return now


def control_loop(fans, sensor, args, shutdown):
    seen_sample = False
    sensor_failed = False
    last_fail_log = None
    while not shutdown.is_set():
        try:
            temp = sensor.read()
        except (OSError, ValueError) as e:
            if not seen_sample:
                last_fail_log = _log_sensor_failure(
                    f"Temperature sensor unavailable: {e}; waiting", last_fail_log)
                shutdown.wait(args.interval)
                continue
            last_fail_log = _log_sensor_failure(
                f"Temperature read failed: {e}; requesting EXTREME cooling",
                last_fail_log)
            sensor_failed = True
            temp = None
        else:
            if sensor_failed:
                log(f"Temperature sensor recovered (temp={temp:g}°C)")
            seen_sample = True
            sensor_failed = False
            last_fail_log = None

        mode = choose_mode(fans.mode, temp, args)
        reason = "sensor unavailable" if temp is None else f"temp={temp:g}°C"
        fans.set_mode(mode, reason)
        shutdown.wait(args.interval)


def run(args):
    shutdown = StopSignal()

    def handle_signal(signum, frame):
        shutdown.set()

    previous_handlers = {}
    previous_wakeup = None
    try:
        previous_wakeup = shutdown.install_wakeup()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, handle_signal)

        with single_instance(), ExitStack() as resources:
            sensor = TemperatureSensor()
            fd = os.open("/dev/port", os.O_RDWR)
            resources.callback(os.close, fd)
            fans = FanController(fd)
            resources.callback(fans.stop)

            sensor_name = sensor.path if sensor.path is not None else "pending"
            log(f"Started: extreme={args.temp_on}/{args.temp_off}°C "
                f"normal={args.temp_normal_on}/{args.temp_normal_off}°C "
                f"interval={args.interval}s sensor={sensor_name}")
            control_loop(fans, sensor, args, shutdown)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if previous_wakeup is not None:
            signal.set_wakeup_fd(previous_wakeup)
        shutdown.close()
    log("Stopped")


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except (OSError, RuntimeError) as e:
        log(f"Cannot run cooling controller: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
