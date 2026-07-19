from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class Signature:
    key_id: str
    value: str
    algorithm: str = "ed25519"


class TrustStore:
    def __init__(self, keys: dict[str, bytes] | None = None) -> None:
        self._keys = dict(keys or {})

    def add(self, key_id: str, public_key: bytes) -> None:
        if not key_id.strip() or len(public_key) != 32:
            raise ValueError("An Ed25519 trust key requires an id and 32 raw bytes")
        self._keys[key_id] = public_key

    def verify(self, payload: bytes, signature: Signature) -> bool:
        if signature.algorithm != "ed25519" or signature.key_id not in self._keys:
            return False
        try:
            value = base64.b64decode(signature.value, validate=True)
            Ed25519PublicKey.from_public_bytes(self._keys[signature.key_id]).verify(value, payload)
            return True
        except (InvalidSignature, ValueError):
            return False

    def export(self) -> dict[str, str]:
        return {key: base64.b64encode(value).decode("ascii") for key, value in self._keys.items()}

    @classmethod
    def from_export(cls, data: dict[str, str]) -> TrustStore:
        return cls({key: base64.b64decode(value, validate=True) for key, value in data.items()})


def sign_payload(private_key: Ed25519PrivateKey, key_id: str, payload: bytes) -> Signature:
    return Signature(key_id, base64.b64encode(private_key.sign(payload)).decode("ascii"))


def public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
