from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from vla_pet.errors import ErrorCategory, PetError
from vla_pet.permissions import Capability, PermissionBroker
from vla_pet.signing import Signature, TrustStore, canonical_json

UPDATE_SCHEMA = "pet.update/v1"


@dataclass(frozen=True, slots=True)
class UpdateArtifact:
    version: str
    channel: str
    url: str
    sha256: str
    size_bytes: int
    minimum_database_schema: int
    release_notes: str = ""


class SignedUpdateClient:
    """Opt-in signed manifest/download verifier; installation remains user-visible."""

    def __init__(self, broker: PermissionBroker, trust_store: TrustStore) -> None:
        self.broker = broker
        self.trust_store = trust_store

    def check(self, manifest_url: str, *, channel: str = "stable") -> UpdateArtifact:
        parsed = urllib.parse.urlparse(manifest_url)
        scope = {"domain": parsed.hostname or "local-file"}
        raw = self.broker.run_authorized(
            Capability.UPDATE_CHECK,
            lambda: self._read_bytes(manifest_url, limit=256 * 1024),
            explicit_user_action=True,
            scope=scope,
        )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.manifest.invalid_json",
                "Update manifest is not valid JSON",
            ) from exc
        if not isinstance(value, dict) or value.get("schema") != UPDATE_SCHEMA:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.manifest.schema",
                "Unsupported update manifest schema",
            )
        signature_raw = value.get("signature")
        if not isinstance(signature_raw, dict):
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "update.signature.required",
                "Update manifest has no signature",
            )
        unsigned = dict(value)
        unsigned.pop("signature", None)
        signature = Signature(
            str(signature_raw.get("key_id", "")),
            str(signature_raw.get("value", "")),
            str(signature_raw.get("algorithm", "ed25519")),
        )
        if not self.trust_store.verify(canonical_json(unsigned), signature):
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "update.signature.invalid",
                "Update signature is invalid or untrusted",
            )
        if value.get("channel") != channel:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.channel.mismatch",
                f"Expected {channel} update channel",
            )
        artifact = value.get("artifact")
        if not isinstance(artifact, dict):
            raise PetError(ErrorCategory.CONFIGURATION, "update.artifact.missing", "Artifact missing")
        version = str(value.get("version", ""))
        try:
            version_tuple(version)
        except ValueError as exc:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.version.invalid",
                "Update version must use major.minor.patch",
            ) from exc
        artifact_url = str(artifact.get("url", ""))
        artifact_scheme = urllib.parse.urlparse(artifact_url).scheme
        sha256 = str(artifact.get("sha256", ""))
        size_bytes = max(0, int(artifact.get("size_bytes", 0)))
        if artifact_scheme not in {"file", "https"}:
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "update.artifact.scheme",
                "Signed artifacts must use a local file or HTTPS URL",
            )
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or not 1 <= size_bytes <= 2**31:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.artifact.invalid",
                "Signed artifact hash or size is invalid",
            )
        return UpdateArtifact(
            version=version,
            channel=str(value["channel"]),
            url=artifact_url,
            sha256=sha256,
            size_bytes=size_bytes,
            minimum_database_schema=max(0, int(value.get("minimum_database_schema", 0))),
            release_notes=str(value.get("release_notes", ""))[:4000],
        )

    def download(self, artifact: UpdateArtifact, destination: Path) -> Path:
        parsed = urllib.parse.urlparse(artifact.url)
        scope = {"domain": parsed.hostname or "local-file"}
        data = self.broker.run_authorized(
            Capability.UPDATE_CHECK,
            lambda: self._read_bytes(artifact.url, limit=artifact.size_bytes),
            explicit_user_action=True,
            scope=scope,
        )
        if artifact.size_bytes and len(data) != artifact.size_bytes:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.size.mismatch",
                "Downloaded artifact size does not match the signed manifest",
            )
        if hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "update.hash.mismatch",
                "Downloaded artifact hash does not match the signed manifest",
            )
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
        destination.chmod(0o600)
        return destination

    @staticmethod
    def _read_bytes(url: str, *, limit: int) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"file", "https"}:
            raise PetError(
                ErrorCategory.PERMISSION_DENIED,
                "update.url.scheme",
                "Only local file and HTTPS update sources are accepted",
            )
        with urllib.request.urlopen(url, timeout=10.0) as response:  # noqa: S310 - scheme checked
            data = response.read(limit + 1)
        if len(data) > limit:
            raise PetError(
                ErrorCategory.CONFIGURATION,
                "update.download.too_large",
                "Update response exceeds its signed size boundary",
            )
        return data


def version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.strip().lstrip("v").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("Version must use major.minor.patch")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]
