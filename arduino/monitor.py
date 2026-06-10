#!/usr/bin/env python3
"""Live terminal monitor for the Arduino blow detector.

Usage:
  python3 arduino/monitor.py
  python3 arduino/monitor.py --port /dev/cu.usbserial-21310
"""

import argparse
import sys
import time
import serial
import serial.tools.list_ports


BAR_WIDTH = 40
MAX_DISPLAY = 200  # clip bar at this level


def find_port() -> str | None:
    keywords = ("arduino", "wch", "ch340", "usb serial", "usb-serial", "cp210", "usb2.0-serial")
    for p in serial.tools.list_ports.comports():
        text = f"{p.description} {p.manufacturer or ''}".lower()
        if any(kw in text for kw in keywords):
            return p.device
    return None


def bar(level: int, threshold: int) -> str:
    filled = min(int(level / MAX_DISPLAY * BAR_WIDTH), BAR_WIDTH)
    thresh_pos = min(int(threshold / MAX_DISPLAY * BAR_WIDTH), BAR_WIDTH)
    cells = []
    for i in range(BAR_WIDTH):
        if i == thresh_pos:
            cells.append("|")
        elif i < filled:
            cells.append("#" if i < thresh_pos else "!")
        else:
            cells.append(".")
    return "".join(cells)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print("No Arduino port found. Use --port /dev/cu.XXXX")
        sys.exit(1)

    print(f"Connecting to {port} @ {args.baud} baud...")
    ser = serial.Serial(port, args.baud, timeout=1)
    print("Connected. Blow into the mic!\n")

    baseline = None
    threshold = None
    level = 0
    last_blow = 0.0

    try:
        while True:
            raw = ser.readline().decode("utf-8", errors="replace").strip()
            if not raw:
                continue

            if raw.startswith("BASELINE,"):
                baseline = int(raw.split(",")[1])
                print(f"  Baseline calibrated: {baseline}")

            elif raw.startswith("LEVEL,"):
                parts = raw.split(",")
                level = int(parts[1])
                threshold = int(parts[2])
                since = time.time() - last_blow
                cooldown = f"  cooldown {since:.1f}s" if since < 4.0 else ""
                line = (
                    f"\r  [{bar(level, threshold)}]"
                    f"  {level:>4}/{threshold:<4}"
                    f"{cooldown}   "
                )
                sys.stdout.write(line)
                sys.stdout.flush()

            elif raw == "BLOW":
                last_blow = time.time()
                sys.stdout.write(f"\r  *** BLOW DETECTED ***{' ' * 30}\n")
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
