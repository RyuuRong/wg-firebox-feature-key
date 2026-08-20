#!/usr/bin/env python3
"""Boot a GParted Live VM over VNC and drop into the root shell.

This drives the GParted Live boot sequence headlessly:

  1. Wait for the syslinux boot menu (default entry times out after 30 s
     into graphical mode, which has no usable video over VNC).
  2. Select "Other modes of GParted Live" -> "Safe graphic settings
     (vga=normal)" (text mode).
  3. Answer the boot dialogs: keymap (Enter), language (Enter) and the
     mode question (Tab + 2 + Enter -> "Enter command line prompt").
  4. Capture a screenshot for verification.

Usage:
    python vnc_boot_menu.py --snapshot boot.png

Afterwards control the shell with vnc_cmd.py / vnc_key.py.
"""

import argparse
import os
import sys
import time

from vncdotool import api


def press(client, keys, pause=0.3):
    for key in keys:
        client.keyPress(key)
        time.sleep(pause)


def send_keys(host, port, password, keys, pause=0.3):
    client = api.connect(f"{host}::{port}", password=password)
    press(client, keys, pause)
    time.sleep(1)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="5900")
    parser.add_argument("--password", default="vncpass123")
    parser.add_argument("--menu-wait", type=float, default=18,
                        help="seconds to wait for the boot menu after power-on")
    parser.add_argument("--boot-wait", type=float, default=50,
                        help="seconds to wait for the boot dialogs after selection")
    parser.add_argument("--snapshot", default="boot.png",
                        help="PNG path of the final verification screenshot")
    args = parser.parse_args()

    print("waiting for the boot menu ...")
    time.sleep(args.menu_wait)
    send_keys(args.host, args.port, args.password,
              ["down", "down", "down", "down", "enter",
               "down", "down", "down", "enter"])

    print("waiting for the boot dialogs ...")
    time.sleep(args.boot_wait)
    send_keys(args.host, args.port, args.password,
              ["enter", "enter", "tab", "2", "enter"])

    print("capturing verification screenshot ...")
    time.sleep(5)
    client = api.connect(f"{args.host}::{args.port}", password=args.password)
    with open(args.snapshot, "wb") as fh:
        client.captureScreen(fh)
    print(f"saved {args.snapshot}")
    print("if the screenshot shows a bash prompt, the shell is ready.")
    os._exit(0)


if __name__ == "__main__":
    main()