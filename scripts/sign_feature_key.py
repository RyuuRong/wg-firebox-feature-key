#!/usr/bin/env python3
"""Sign a WatchGuard Firebox feature key file (pure cryptography variant).

NOTE: requires cryptography < 48 (newer releases removed the sect163k1
curve). Prefer sign_openssl.py with OpenSSL 3.x.

Usage:
    python sign_feature_key.py <feature_key_file> <private_key.pem>
"""

import os
import sys

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes


def inst_symbol(my_str, group=16, char="-"):
    my_str = str(my_str)
    return char.join(my_str[i:i + group] for i in range(0, len(my_str), group))


def main():
    if len(sys.argv) != 3:
        print(
            f"Usage: {os.path.basename(sys.argv[0])} <feature_key_file> <private_key.pem>",
            file=sys.stderr,
        )
        sys.exit(1)

    feature_key = open(sys.argv[1], "r").read()
    private_key = load_pem_private_key(open(sys.argv[2], "rb").read(), password=None)

    signature_start = feature_key.find("Signature:")
    if signature_start == -1:
        raise ValueError("Signature field not found in the license data.")

    data_before_signature = feature_key[:signature_start]

    license_normalized = b"".join(
        char.encode() for char in data_before_signature
        if char not in ("\t", "\n", "\x0b", "\x0c", "\r", " ")
    )

    signature = private_key.sign(license_normalized, ec.ECDSA(hashes.SHA1()))
    new_signature = "Signature: " + inst_symbol(signature.hex(), 16, "-")
    print(new_signature)

    with open(sys.argv[1], "w", newline="\n") as fh:
        fh.write(data_before_signature + new_signature)
    print(f"Signature in file {sys.argv[1]} overwritten")


if __name__ == "__main__":
    main()