#!/usr/bin/env python3
"""Type a command line into a VMware VNC console (root shell) and press Enter.

Usage:
    python vnc_cmd.py --text "ls /"
    python vnc_cmd.py --text "wget 10.0.1.2/key.pem"

Only characters that survive the VMware VNC keysym mapping should be used:
lowercase letters, digits, space, - / . ; Tab/Enter are fine. Characters
that need shift (>, :, =, |, uppercase) are corrupted by the VNC server.
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
    parser.add_argument("--text", required=True)
    parser.add_argument("--char-pause", type=float, default=0.03,
                        help="seconds between keystrokes")
    args = parser.parse_args()

    client = api.connect(f"{args.host}::{args.port}", password=args.password)
    for char in args.text:
        client.keyPress(char)
        time.sleep(args.char_pause)
    client.keyPress("enter")
    time.sleep(0.5)
    os._exit(0)


if __name__ == "__main__":
    main()