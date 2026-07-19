from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from vla_pet.signing import canonical_json, public_key_bytes, sign_payload


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Create a signed vla-pet update manifest")
    value.add_argument("--artifact", type=Path, required=True)
    value.add_argument("--version", required=True)
    value.add_argument("--artifact-url", required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--private-key", type=Path, required=True)
    value.add_argument("--public-key", type=Path)
    value.add_argument("--key-id", default="vla-pet-release")
    value.add_argument("--channel", choices=("stable", "beta", "nightly"), default="stable")
    value.add_argument("--generate-key", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.generate_key:
        private = Ed25519PrivateKey.generate()
        raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        descriptor = os.open(args.private_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
    else:
        private = Ed25519PrivateKey.from_private_bytes(args.private_key.read_bytes())
    artifact = args.artifact.resolve()
    payload = {
        "schema": "pet.update/v1",
        "version": args.version,
        "channel": args.channel,
        "minimum_database_schema": 2,
        "release_notes": f"vla-pet {args.version}",
        "artifact": {
            "url": args.artifact_url,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        },
    }
    signature = sign_payload(private, args.key_id, canonical_json(payload))
    payload["signature"] = {
        "algorithm": signature.algorithm,
        "key_id": signature.key_id,
        "value": signature.value,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.public_key:
        args.public_key.write_text(
            base64.b64encode(public_key_bytes(private)).decode("ascii") + "\n",
            encoding="ascii",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
