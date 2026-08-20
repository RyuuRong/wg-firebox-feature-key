#!/usr/bin/env python3
"""Sign a WatchGuard Firebox feature key file with an EC private key.

Uses OpenSSL 3.x (the curve sect163k1 is not supported by cryptography >= 48).

Usage:
    python sign_openssl.py <feature_key_file> <private_key.pem>

How it works:
    1. All whitespace characters (space, tab, CR, LF, VT, FF) are removed
       from the license text up to (excluding) the "Signature:" marker.
    2. An ECDSA-SHA1 signature is computed over the normalized bytes.
    3. The "Signature:" line in the input file is overwritten (in place)
       with the hex signature grouped in 16-character blocks joined by "-".

The OpenSSL binary is taken from the OPENSSL environment variable, then
PATH, then the Git-for-Windows default location.
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
    """Return the license bytes up to 'Signature:' with all whitespace removed."""
    signature_start = text.find("Signature:")
    if signature_start == -1:
        raise ValueError("Signature field not found in the license data.")
    data_before_signature = text[:signature_start]
    return b"".join(
        char.encode() for char in data_before_signature
        if char not in ("\t", "\n", "\x0b", "\x0c", "\r", " ")
    )


def format_signature(signature_hex):
    return "-".join(signature_hex[i:i + 16] for i in range(0, len(signature_hex), 16))


def main():
    if len(sys.argv) != 3:
        print(
            f"Usage: {os.path.basename(sys.argv[0])} <feature_key_file> <private_key.pem>",
            file=sys.stderr,
        )
        sys.exit(1)

    feature_key_file, private_key_path = sys.argv[1], sys.argv[2]
    feature_key = open(feature_key_file, "r").read()

    signature_start = feature_key.find("Signature:")
    if signature_start == -1:
        raise ValueError("Signature field not found in the license data.")
    data_before_signature = feature_key[:signature_start]

    license_normalized = normalize_license(feature_key)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(license_normalized)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [OPENSSL, "dgst", "-sha1", "-sign", private_key_path, tmp_path],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        signature = result.stdout
    finally:
        os.unlink(tmp_path)

    new_signature = "Signature: " + format_signature(signature.hex())
    with open(feature_key_file, "w", newline="\n") as fh:
        fh.write(data_before_signature + new_signature)

    print(new_signature)
    print(f"Signature in file {feature_key_file} overwritten")


if __name__ == "__main__":
    main()