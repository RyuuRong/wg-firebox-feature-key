#!/usr/bin/env python3
"""Press one or more keys on a VMware VNC console.

Usage:
    python vnc_key.py --keys enter
    python vnc_key.py --keys down --count 4
    python vnc_key.py --keys tab 2 enter

Examples of key names: enter, tab, down, up, left, right, space,
escape, and any single character ("2", "a", "9", ...).

Note: VMware's VNC server drops shift state for most keysyms, so
shift-dependent characters (>, :, =, |, uppercase letters) will be
corrupted. Prefer lowercase + - / . and Enter/Tab/arrows.
"""

import argparse
import os
import sys
import time

from vncdotool import api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="5900")
    parser.add_argument("--password", default="vncpass123")
    parser.add_argument("--keys", nargs="+", required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--pause", type=float, default=0.2,
                        help="seconds between repetitions")
    args = parser.parse_args()

    client = api.connect(f"{args.host}::{args.port}", password=args.password)
    for _ in range(args.count):
        for key in args.keys:
            client.keyPress(key)
            time.sleep(args.pause)
    time.sleep(0.5)
    os._exit(0)


if __name__ == "__main__":
    main()