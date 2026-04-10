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
            with open(path, 'r') as f:
                if "k10temp" in f.read():
                    return path.replace("name", "temp1_input")
        except: continue
    return None

def ec_wait(fd, flag, value):
    for _ in range(100):
        os.lseek(fd, EC_SC, os.SEEK_SET)
        status = ord(os.read(fd, 1))
        if ((status >> flag) & 0x1) == value:
            return True
        time.sleep(0.001)
    return False

# Writes to the EC register without portio
def ec_write(fd, port, value):
    if ec_wait(fd, IBF, 0):
        os.lseek(fd, EC_SC, os.SEEK_SET)
        os.write(fd, bytes([WR_EC]))
    if ec_wait(fd, IBF, 0):
        os.lseek(fd, EC_DATA, os.SEEK_SET)
        os.write(fd, bytes([port]))
    if ec_wait(fd, IBF, 0):
        os.lseek(fd, EC_DATA, os.SEEK_SET)
        os.write(fd, bytes([value]))

def main():
    temp_path = get_cpu_temp_path()
    if not temp_path: return

    with open("/dev/port", "rb+", buffering=0) as f:
        fd = f.fileno()
        is_active = False
        
        while True:
            try:
                with open(temp_path, "r") as tf:
                    temp = int(tf.read()) / 1000
            except: temp = 0

            if temp >= TEMP_ON and not is_active:
                ec_write(fd, EXTREME_COOLING_REGISTER, ACTIVATE)
                is_active = True
            elif temp <= TEMP_OFF and is_active:
                ec_write(fd, EXTREME_COOLING_REGISTER, DEACTIVATE)
                is_active = False
            
            with open("/tmp/ec_fan_status", "w") as sf:
                sf.write("ON" if is_active else "OFF")
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
