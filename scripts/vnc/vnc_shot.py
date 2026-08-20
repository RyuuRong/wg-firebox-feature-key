#!/usr/bin/env python3
"""Capture the VMware VNC console as a PNG image.

Usage:
    python vnc_shot.py --output shot.png

Useful to verify the state of the guest (e.g. with an OCR tool) when
driving the procedure headlessly.
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
    parser.add_argument("--output", required=True, help="path of the PNG to write")
    args = parser.parse_args()

    client = api.connect(f"{args.host}::{args.port}", password=args.password)
    time.sleep(1)
    with open(args.output, "wb") as fh:
        client.captureScreen(fh)
    print(f"saved {args.output}")
    os._exit(0)


if __name__ == "__main__":
    main()