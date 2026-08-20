#!/usr/bin/env python3
"""Verify a WatchGuard Firebox feature key signature (pure cryptography variant).

NOTE: requires cryptography < 48 (newer releases removed the sect163k1
curve). Prefer verify_openssl.py with OpenSSL 3.x.

Usage:
    python verify_feature_key.py <feature_key_file> <public_key.pem>
"""

import os
import sys

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature


def main():
    if len(sys.argv) != 3:
        print(
            f"Usage: {os.path.basename(sys.argv[0])} <feature_key_file> <public_key.pem>",
            file=sys.stderr,
        )
        sys.exit(1)

    feature_key = open(sys.argv[1], "r").read()
    public_key = load_pem_public_key(open(sys.argv[2], "rb").read())

    signature_start = feature_key.find("Signature:")
    if signature_start == -1:
        raise ValueError("Signature field not found in the license data.")

    data_before_signature = feature_key[:signature_start]
    data_after_signature = feature_key[signature_start + len("Signature:"):]

    license_normalized = b"".join(
        char.encode() for char in data_before_signature
        if char not in ("\t", "\n", "\x0b", "\x0c", "\r", " ")
    )
    signature = bytes.fromhex(data_after_signature.strip().replace("-", ""))

    try:
        public_key.verify(signature, license_normalized, ec.ECDSA(hashes.SHA1()))
        print("Success! This is correct feature key")
    except InvalidSignature:
        print("Invalid Signature. Verification of Feature Key Failed")
        sys.exit(1)


if __name__ == "__main__":
    main()