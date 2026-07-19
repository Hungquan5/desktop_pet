from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import QCoreApplication

from vla_pet.cli import _update_source_url
from vla_pet.errors import PetError
from vla_pet.permissions import Capability, PermissionBroker, PermissionLifetime
from vla_pet.signing import TrustStore, canonical_json, public_key_bytes, sign_payload
from vla_pet.update_service import AsyncUpdateChecker
from vla_pet.updater import SignedUpdateClient, version_tuple


def test_cli_normalizes_bare_update_manifest_path(tmp_path: Path) -> None:
    manifest = tmp_path / "update.json"
    assert _update_source_url(str(manifest)) == manifest.resolve().as_uri()
    assert _update_source_url("https://updates.example/pet.json") == (
        "https://updates.example/pet.json"
    )


def make_manifest(tmp_path: Path) -> tuple[Path, Path, TrustStore]:
    artifact = tmp_path / "pet.whl"
    artifact.write_bytes(b"signed wheel bytes")
    private = Ed25519PrivateKey.generate()
    trust = TrustStore({"release": public_key_bytes(private)})
    import hashlib

    value = {
        "schema": "pet.update/v1",
        "version": "1.0.1",
        "channel": "stable",
        "minimum_database_schema": 2,
        "release_notes": "Test update",
        "artifact": {
            "url": artifact.as_uri(),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size_bytes": artifact.stat().st_size,
        },
    }
    signature = sign_payload(private, "release", canonical_json(value))
    value["signature"] = {"key_id": signature.key_id, "value": signature.value}
    manifest = tmp_path / "update.json"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    return manifest, artifact, trust


def test_signed_local_update_check_and_download(tmp_path: Path) -> None:
    manifest, artifact, trust = make_manifest(tmp_path)
    broker = PermissionBroker()
    broker.grant(
        Capability.UPDATE_CHECK,
        lifetime=PermissionLifetime.SESSION,
        scope={"domain": "local-file"},
    )
    client = SignedUpdateClient(broker, trust)
    update = client.check(manifest.as_uri())
    downloaded = client.download(update, tmp_path / "downloads" / "pet.whl")
    assert downloaded.read_bytes() == artifact.read_bytes()
    assert version_tuple(update.version) > version_tuple("1.0.0")


def test_tampered_or_denied_update_never_downloads(tmp_path: Path) -> None:
    manifest, _artifact, trust = make_manifest(tmp_path)
    denied = SignedUpdateClient(PermissionBroker(), trust)
    with pytest.raises(PetError):
        denied.check(manifest.as_uri())
    value = json.loads(manifest.read_text())
    value["version"] = "9.9.9"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    broker = PermissionBroker()
    broker.grant(Capability.UPDATE_CHECK, scope={"domain": "local-file"})
    with pytest.raises(PetError) as error:
        SignedUpdateClient(broker, trust).check(manifest.as_uri())
    assert error.value.code == "update.signature.invalid"


def test_signed_update_rejects_unsafe_artifact_fields(tmp_path: Path) -> None:
    manifest, _artifact, trust = make_manifest(tmp_path)
    value = json.loads(manifest.read_text())
    value["artifact"]["url"] = "http://example.test/pet.whl"
    private = Ed25519PrivateKey.generate()
    trust = TrustStore({"release": public_key_bytes(private)})
    unsigned = dict(value)
    unsigned.pop("signature")
    signature = sign_payload(private, "release", canonical_json(unsigned))
    value["signature"] = {"key_id": signature.key_id, "value": signature.value}
    manifest.write_text(json.dumps(value), encoding="utf-8")
    broker = PermissionBroker()
    broker.grant(Capability.UPDATE_CHECK, scope={"domain": "local-file"})
    with pytest.raises(PetError) as error:
        SignedUpdateClient(broker, trust).check(manifest.as_uri())
    assert error.value.code == "update.artifact.scheme"


def test_opt_in_update_check_runs_off_thread(tmp_path: Path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    manifest, _artifact, trust = make_manifest(tmp_path)
    broker = PermissionBroker()
    broker.grant(Capability.UPDATE_CHECK, scope={"domain": "local-file"})
    checker = AsyncUpdateChecker(broker, "1.0.0")
    finished: list[tuple[object, str]] = []
    checker.finished.connect(lambda artifact, error: finished.append((artifact, error)))
    started = time.monotonic()
    assert checker.check(
        manifest.as_uri(),
        trust.export()["release"],
        key_id="release",
        channel="stable",
    )
    assert time.monotonic() - started < 0.1
    deadline = time.monotonic() + 3.0
    while not finished and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    checker.close()
    assert finished and not finished[0][1]
    assert finished[0][0].version == "1.0.1"
