#!/usr/bin/python3
import time
import os
import glob

# Address constants from Alberto Vicente/ExtremeCooling4Linux GitLab
EC_SC = 0x66
EC_DATA = 0x62
IBF = 1
OBF = 0
RD_EC = 0x80
WR_EC = 0x81
EXTREME_COOLING_REGISTER = 0xBD
ACTIVATE = 0x40
DEACTIVATE = 0x00

# Temperature thresholds
TEMP_ON = 70
TEMP_OFF = 60

# Interval between temperature checks
INTERVAL = 5

# Finds CPU temperature sensor path
def get_cpu_temp_path():
    for path in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            with open(path, "r") as f:
                if "k10temp" in f.read():
                    return path.replace("name", "temp1_input")
        except OSError:
            continue
    return None

def ec_wait(fd, flag, value):
    for _ in range(100):
        status = os.pread(fd, 1, EC_SC)[0]
        if ((status >> flag) & 0x1) == value:
            return True
        time.sleep(0.001)
    return False

# Writes to the EC register without portio
def ec_write(fd, port, value):
    if ec_wait(fd, IBF, 0):
        os.pwrite(fd, bytes([WR_EC]), EC_SC)
    if ec_wait(fd, IBF, 0):
        os.pwrite(fd, bytes([port]), EC_DATA)
    if ec_wait(fd, IBF, 0):
        os.pwrite(fd, bytes([value]), EC_DATA)

def main():
    temp_path = get_cpu_temp_path()
    if not temp_path:
        return

    port_fd = os.open("/dev/port", os.O_RDWR)
    temp_fd = os.open(temp_path, os.O_RDONLY)
    try:
        is_active = False
        while True:
            try:
                temp = int(os.pread(temp_fd, 16, 0)) / 1000
            except (OSError, ValueError):
                temp = 0

            if temp >= TEMP_ON and not is_active:
                ec_write(port_fd, EXTREME_COOLING_REGISTER, ACTIVATE)
                is_active = True
            elif temp <= TEMP_OFF and is_active:
                ec_write(port_fd, EXTREME_COOLING_REGISTER, DEACTIVATE)
                is_active = False

            time.sleep(INTERVAL)
    finally:
        os.close(temp_fd)
        os.close(port_fd)

if __name__ == "__main__":
    main()
