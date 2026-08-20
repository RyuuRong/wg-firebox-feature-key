#!/usr/bin/env python3
"""Verify the signature of a WatchGuard Firebox feature key file.

Usage:
    python verify_openssl.py <feature_key_file> <public_key.pem>

Prints "Success! This is correct feature key" when the signature validates
against the given public key, otherwise "Invalid Signature...".
"""

import os
import shutil
import subprocess
import sys
import tempfile

OPENSSL = (
    os.environ.get("OPENSSL")
    or shutil.which("openssl")
    or r"C:\Program Files\Git\usr\bin\openssl.exe"
)


def normalize_license(text):
    signature_start = text.find("Signature:")
    if signature_start == -1:
        raise ValueError("Signature field not found in the license data.")
    data_before_signature = text[:signature_start]
    return b"".join(
        char.encode() for char in data_before_signature
        if char not in ("\t", "\n", "\x0b", "\x0c", "\r", " ")
    )


def main():
    if len(sys.argv) != 3:
        print(
            f"Usage: {os.path.basename(sys.argv[0])} <feature_key_file> <public_key.pem>",
            file=sys.stderr,
        )
        sys.exit(1)

    feature_key_file, public_key_path = sys.argv[1], sys.argv[2]
    feature_key = open(feature_key_file, "r").read()

    signature_start = feature_key.find("Signature:")
    if signature_start == -1:
        raise ValueError("Signature field not found in the license data.")

    data_after_signature = feature_key[signature_start + len("Signature:"):]
    license_normalized = normalize_license(feature_key)
    signature = bytes.fromhex(data_after_signature.strip().replace("-", ""))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(license_normalized)
        data_path = tmp.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(signature)
        sig_path = tmp.name

    try:
        result = subprocess.run(
            [OPENSSL, "dgst", "-sha1", "-verify", public_key_path,
             "-signature", sig_path, data_path],
            capture_output=True,
        )
        output = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
        if result.returncode == 0 and "Verified OK" in output:
            print("Success! This is correct feature key")
        else:
            print("Invalid Signature. Verification of Feature Key Failed")
            print(output)
    finally:
        os.unlink(data_path)
        os.unlink(sig_path)


if __name__ == "__main__":
    main()